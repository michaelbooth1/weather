"""Anti-regrowth ratchet for test modules (test-suite review K, role 21; PROPOSAL until owner approval).

Every rule is an AST count per test module. ``tests/hygiene_ratchet_baseline.json`` records today's
counts; the ratchet fails only when a module's count rises above its baseline entry (a module without an
entry is allowed 0). Lowering a count never fails. Rules:

- ``guards_declaration``: the module docstring has no ``Guards:`` line naming the contract or incident
  the module protects (1 per module).
- ``ps1_substring_without_execution``: asserts that apply ``in``/``not in``, ``count``/``find``/
  ``index``/``startswith``/``endswith`` or ``re.search``-style calls to text read from a ``.ps1`` file,
  in a module that never spawns PowerShell (no execution twin in the same module).
- ``private_src_import``: names starting with ``_`` (or modules with a ``_`` segment) imported from a
  product package (``src/`` packages and ``app``).
- ``unmarked_spawning_test``: test functions that spawn ``git`` or PowerShell (directly, through a
  same-module helper, or through a same-module fixture) and carry no ``pytest.mark.spawns`` (on the
  test, its class, or the module's ``pytestmark``).

Limits (by design; this is a regrowth brake, not a proof): helpers imported from other test modules are
not followed, command lines built in another module are not resolved, and the ``pytest.raises(match=)``
guideline is reported (``raises_match`` in ``--report``) but is not a rule, because whether the code under
test is a fail-closed gate is not visible in the AST.

Commands (repository root)::

    python -m tests.hygiene_ratchet --report        # counts per rule and the growth check
    python -m tests.hygiene_ratchet --tighten       # lower baseline entries to today's counts
    python -m tests.hygiene_ratchet --write-baseline  # reset; owner-approved resets only
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from weather.paths import REPO_ROOT

TESTS_ROOT = REPO_ROOT / "tests"
BASELINE_PATH = TESTS_ROOT / "hygiene_ratchet_baseline.json"
BASELINE_SCHEMA = "test_hygiene_ratchet_baseline_v1"

RULES = (
    "guards_declaration",
    "ps1_substring_without_execution",
    "private_src_import",
    "unmarked_spawning_test",
)
RULE_HELP = {
    "guards_declaration": (
        "add a module docstring line 'Guards: <contract, EF/RF/HWGTW id, incident or owning doc section>'"
    ),
    "ps1_substring_without_execution": (
        "assert the script's behaviour by executing it (see tests/AGENTS.md); a .ps1 text assert is "
        "allowed only in a module that also runs PowerShell"
    ),
    "private_src_import": "test through the public name, or make the helper public in its owner module",
    "unmarked_spawning_test": "add @pytest.mark.spawns to the test, its class, or the module pytestmark",
}

GUARDS_TAG = "guards:"
GUARDS_MIN_TEXT = 8
SUBPROCESS_FUNCS = {"run", "Popen", "call", "check_call", "check_output"}
SPAWN_DOTTED = {f"subprocess.{name}" for name in SUBPROCESS_FUNCS} | {
    "os.system",
    "os.popen",
    "asyncio.create_subprocess_exec",
    "asyncio.create_subprocess_shell",
}
# Test-helper modules whose calls always start a process of the given kind.
SPAWN_HELPER_MODULES = {"tests.powershell_host": "powershell", "tests.git_template": "git"}
READ_ATTRS = {"read_text", "read", "read_bytes", "readlines"}
TEXT_PROBE_ATTRS = {"count", "find", "rfind", "index", "rindex", "startswith", "endswith"}
REGEX_ATTRS = {"search", "findall", "match", "fullmatch", "finditer", "sub", "split"}


def product_roots(repo_root: Path = REPO_ROOT) -> frozenset[str]:
    src = repo_root / "src"
    roots = {p.name for p in src.iterdir() if p.is_dir() and (p / "__init__.py").is_file()} if src.is_dir() else set()
    return frozenset(roots | {"app"})


def dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _is_private(segment: str) -> bool:
    return segment.startswith("_") and not (segment.startswith("__") and segment.endswith("__"))


def _walk_no_defs(node: ast.AST) -> Iterator[ast.AST]:
    """ast.walk that does not enter nested function or class bodies."""
    stack = list(ast.iter_child_nodes(node))
    while stack:
        child = stack.pop()
        yield child
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(child))


def _module_statements(tree: ast.Module) -> Iterator[ast.AST]:
    yield from _walk_no_defs(tree)


@dataclass
class ModuleFacts:
    counts: dict[str, int] = field(default_factory=dict)
    raises_match: int = 0
    details: dict[str, list[int]] = field(default_factory=dict)

    def add(self, rule: str, line: int, amount: int = 1) -> None:
        self.counts[rule] = self.counts.get(rule, 0) + amount
        self.details.setdefault(rule, []).append(line)


# ----------------------------------------------------------------------------------------------- guards
def has_guards_declaration(tree: ast.Module) -> bool:
    doc = ast.get_docstring(tree, clean=True) or ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(GUARDS_TAG) and len(stripped[len(GUARDS_TAG):].strip()) >= GUARDS_MIN_TEXT:
            return True
    return False


# ------------------------------------------------------------------------------------- private imports
def private_src_imports(tree: ast.Module, roots: frozenset[str]) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            segments = node.module.split(".")
            if segments[0] not in roots:
                continue
            if any(_is_private(s) for s in segments):
                lines.extend(node.lineno for _ in node.names)
                continue
            lines.extend(node.lineno for alias in node.names if _is_private(alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                segments = alias.name.split(".")
                if segments[0] in roots and any(_is_private(s) for s in segments):
                    lines.append(node.lineno)
    return lines


# ---------------------------------------------------------------------------------------------- spawns
def _imported_spawn_names(tree: ast.Module) -> tuple[dict[str, str], set[str]]:
    """Names bound to spawn helpers ({name: kind}) and bare subprocess functions."""
    helpers: dict[str, str] = {}
    bare_subprocess: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "subprocess":
                bare_subprocess.update(a.asname or a.name for a in node.names if a.name in SUBPROCESS_FUNCS)
            kind = SPAWN_HELPER_MODULES.get(node.module)
            if kind:
                helpers.update({a.asname or a.name: kind for a in node.names})
            for alias in node.names:
                full = f"{node.module}.{alias.name}"
                if full in SPAWN_HELPER_MODULES:
                    helpers[alias.asname or alias.name] = SPAWN_HELPER_MODULES[full]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in SPAWN_HELPER_MODULES:
                    helpers[alias.asname or alias.name] = SPAWN_HELPER_MODULES[alias.name]
    return helpers, bare_subprocess


def _string_kinds(node: ast.AST, constant_kinds: dict[str, set[str]]) -> set[str]:
    kinds: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            value = sub.value.strip().lower()
            if value in {"git", "git.exe"} or value.startswith("git ") or value.endswith(("\\git.exe", "/git")):
                kinds.add("git")
            if "powershell" in value or "pwsh" in value:
                kinds.add("powershell")
        name = sub.id if isinstance(sub, ast.Name) else sub.attr if isinstance(sub, ast.Attribute) else None
        if name:
            lowered = name.lower()
            if "powershell" in lowered or "pwsh" in lowered:
                kinds.add("powershell")
            kinds |= constant_kinds.get(name, set())
    return kinds


def _is_spawn_call(call: ast.Call, helpers: dict[str, str], bare: set[str]) -> tuple[bool, set[str]]:
    name = dotted(call.func)
    if name is None:
        return False, set()
    if name in SPAWN_DOTTED or name in bare:
        return True, set()
    root = name.split(".")[0]
    if root in helpers:
        return True, {helpers[root]}
    return False, set()


@dataclass
class _Func:
    node: ast.FunctionDef | ast.AsyncFunctionDef
    is_fixture: bool
    fixture_name: str | None
    autouse: bool


def _fixture_info(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[bool, str | None, bool]:
    for dec in fn.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if (dotted(target) or "").split(".")[-1] != "fixture":
            continue
        name, autouse = fn.name, False
        if isinstance(dec, ast.Call):
            for kw in dec.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    name = kw.value.value
                if kw.arg == "autouse" and isinstance(kw.value, ast.Constant):
                    autouse = bool(kw.value.value)
        return True, name, autouse
    return False, None, False


def _marks(decorators: Iterable[ast.expr]) -> set[str]:
    found: set[str] = set()
    for dec in decorators:
        target = dec.func if isinstance(dec, ast.Call) else dec
        parts = (dotted(target) or "").split(".")
        if len(parts) >= 2 and parts[-2] == "mark":
            found.add(parts[-1])
    return found


def _pytestmark_marks(body: Iterable[ast.stmt]) -> set[str]:
    found: set[str] = set()
    for stmt in body:
        targets: list[ast.expr] = []
        if isinstance(stmt, ast.Assign):
            targets = list(stmt.targets)
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets = [stmt.target]
        if any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets):
            value = stmt.value
            elements = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
            found |= _marks(e for e in elements if e is not None)
    return found


def _iter_tests(tree: ast.Module) -> Iterator[tuple[ast.FunctionDef | ast.AsyncFunctionDef, set[str]]]:
    """Test functions with the marks inherited from enclosing classes."""

    def walk_class(cls: ast.ClassDef, inherited: set[str]) -> Iterator[tuple[ast.FunctionDef | ast.AsyncFunctionDef, set[str]]]:
        marks = inherited | _marks(cls.decorator_list) | _pytestmark_marks(cls.body)
        for item in cls.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test"):
                yield item, marks
            elif isinstance(item, ast.ClassDef) and item.name.startswith("Test"):
                yield from walk_class(item, marks)

    module_marks = _pytestmark_marks(tree.body)
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test"):
            yield item, module_marks
        elif isinstance(item, ast.ClassDef) and item.name.startswith("Test"):
            yield from walk_class(item, module_marks)


def spawning_functions(tree: ast.Module) -> dict[str, set[str]]:
    """Map of function or fixture name -> spawn kinds ('git', 'powershell') reached inside this module."""
    helpers, bare = _imported_spawn_names(tree)
    constant_kinds: dict[str, set[str]] = {}
    for stmt in tree.body:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None:
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            kinds = _string_kinds(stmt.value, {})
            if kinds:
                for t in targets:
                    if isinstance(t, ast.Name):
                        constant_kinds[t.id] = kinds
    funcs: list[_Func] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            is_fixture, fixture_name, autouse = _fixture_info(node)
            funcs.append(_Func(node, is_fixture, fixture_name, autouse))
    by_name: dict[str, list[_Func]] = {}
    for f in funcs:
        by_name.setdefault(f.node.name, []).append(f)
    fixtures = {f.fixture_name: f for f in funcs if f.is_fixture and f.fixture_name}

    # "process" marks a function that reaches any spawn; the process kind ('git' / 'powershell') comes
    # from the strings and names of every function on the path, so a generic run(cmd) helper called
    # with a PowerShell command line still counts as PowerShell for its caller.
    own_kinds: dict[int, set[str]] = {}
    resolved: dict[int, set[str]] = {}
    calls: dict[int, set[str]] = {}
    for f in funcs:
        kinds: set[str] = set()
        called: set[str] = set()
        for sub in ast.walk(f.node):
            if isinstance(sub, ast.Call):
                is_spawn, helper_kinds = _is_spawn_call(sub, helpers, bare)
                if is_spawn:
                    kinds |= {"process"} | helper_kinds
                func_name = sub.func.id if isinstance(sub.func, ast.Name) else (
                    sub.func.attr if isinstance(sub.func, ast.Attribute) else None
                )
                if func_name and func_name != f.node.name:
                    called.add(func_name)
        own_kinds[id(f.node)] = _string_kinds(f.node, constant_kinds)
        resolved[id(f.node)] = kinds | (own_kinds[id(f.node)] if kinds else set())
        params = {a.arg for a in f.node.args.args + f.node.args.kwonlyargs + f.node.args.posonlyargs}
        calls[id(f.node)] = called | {f"fixture:{p}" for p in params}

    changed = True
    while changed:
        changed = False
        for f in funcs:
            current = resolved[id(f.node)]
            before = len(current)
            for ref in calls[id(f.node)]:
                if ref.startswith("fixture:"):
                    targets = [fixtures[key]] if (key := ref.removeprefix("fixture:")) in fixtures else []
                else:
                    targets = by_name.get(ref, [])
                for target in targets:
                    if target.node is not f.node:
                        current |= resolved[id(target.node)]
            if "process" in current:
                current |= own_kinds[id(f.node)]
            if len(current) != before:
                changed = True
    autouse_kinds: set[str] = set()
    for f in funcs:
        if f.autouse:
            autouse_kinds |= resolved[id(f.node)]
    result: dict[str, set[str]] = {}
    for f in funcs:
        kinds = resolved[id(f.node)] | (autouse_kinds if f.node.name.startswith("test") else set())
        kinds &= {"git", "powershell"}
        if kinds:
            result.setdefault(f.node.name, set()).update(kinds)
    return result


def unmarked_spawning_tests(tree: ast.Module) -> list[int]:
    spawning = spawning_functions(tree)
    lines = []
    for test, inherited in _iter_tests(tree):
        if test.name in spawning and "spawns" not in (inherited | _marks(test.decorator_list)):
            lines.append(test.lineno)
    return lines


def module_runs_powershell(tree: ast.Module) -> bool:
    return any("powershell" in kinds for kinds in spawning_functions(tree).values())


# ----------------------------------------------------------------------------------- .ps1 text asserts
def _has_ps1_literal(node: ast.AST, path_names: set[str]) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and ".ps1" in sub.value.lower():
            return True
        if isinstance(sub, ast.Name) and sub.id in path_names:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr in path_names:
            return True
    return False


def _is_read_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Attribute) and node.func.attr in READ_ATTRS:
        return True
    return isinstance(node.func, ast.Name) and node.func.id == "open"


class _Ps1Taint:
    def __init__(self, tree: ast.Module) -> None:
        self.tree = tree
        self.global_paths: set[str] = set()
        self.global_text: set[str] = set()
        self.text_funcs: set[str] = set()
        self.functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        self._locals: dict[int, tuple[set[str], set[str]]] = {}
        for _ in range(6):
            before = (len(self.global_paths), len(self.global_text), len(self.text_funcs))
            self._scope(list(_module_statements(tree)), self.global_paths, self.global_text)
            for fn in self.functions:
                paths, text = self._locals.setdefault(id(fn), (set(), set()))
                self._scope(list(ast.walk(fn)), paths, text)
                returns = [n.value for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]
                if any(self.is_text(r, paths, text) for r in returns):
                    self.text_funcs.add(fn.name)
            if before == (len(self.global_paths), len(self.global_text), len(self.text_funcs)):
                break

    def is_text(self, node: ast.AST, paths: set[str], text: set[str]) -> bool:
        all_paths = paths | self.global_paths
        all_text = text | self.global_text
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in all_text:
                return True
            if _is_read_call(sub) and _has_ps1_literal(sub, all_paths):
                return True
            if isinstance(sub, ast.Call):
                name = dotted(sub.func) or ""
                if name.split(".")[-1] in self.text_funcs:
                    return True
        return False

    def _scope(self, nodes: list[ast.AST], paths: set[str], text: set[str]) -> None:
        for node in nodes:
            targets: list[ast.expr] = []
            value: ast.AST | None = None
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
                targets, value = [node.target], node.value
            elif isinstance(node, ast.NamedExpr):
                targets, value = [node.target], node.value
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                targets, value = [node.target], node.iter
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                targets, value = [node.optional_vars], node.context_expr
            if value is None:
                continue
            names = [n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)]
            if self.is_text(value, paths, text):
                text.update(names)
            elif _has_ps1_literal(value, paths | self.global_paths):
                is_handle = isinstance(node, ast.withitem)
                reads = any(_is_read_call(s) for s in ast.walk(value))
                runs = any(
                    isinstance(s, ast.Call) and (dotted(s.func) or "").split(".")[0] == "subprocess"
                    for s in ast.walk(value)
                )
                if is_handle or not (reads or runs):
                    paths.update(names)

    def scope_of(self, assert_node: ast.Assert) -> tuple[set[str], set[str]]:
        best: tuple[set[str], set[str]] = (set(), set())
        best_span = None
        for fn in self.functions:
            end = getattr(fn, "end_lineno", fn.lineno)
            if fn.lineno <= assert_node.lineno <= end:
                span = end - fn.lineno
                if best_span is None or span < best_span:
                    best, best_span = self._locals.get(id(fn), (set(), set())), span
        return best

    def asserts_on_text(self) -> list[int]:
        lines = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Assert):
                continue
            paths, text = self.scope_of(node)
            if self._probes_text(node.test, paths, text):
                lines.append(node.lineno)
        return lines

    def _probes_text(self, test: ast.AST, paths: set[str], text: set[str]) -> bool:
        for sub in ast.walk(test):
            if isinstance(sub, ast.Compare):
                for op, right in zip(sub.ops, sub.comparators):
                    if isinstance(op, (ast.In, ast.NotIn)) and self.is_text(right, paths, text):
                        return True
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                attr = sub.func.attr
                if attr in TEXT_PROBE_ATTRS and self.is_text(sub.func.value, paths, text):
                    return True
                if attr in REGEX_ATTRS and any(self.is_text(a, paths, text) for a in sub.args):
                    return True
        return False


def ps1_text_asserts(tree: ast.Module) -> list[int]:
    return _Ps1Taint(tree).asserts_on_text()


# ------------------------------------------------------------------------------------------ guideline
def raises_with_match(tree: ast.Module) -> int:
    total = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (dotted(node.func) or "").endswith("raises"):
            if any(kw.arg == "match" for kw in node.keywords):
                total += 1
    return total


# ------------------------------------------------------------------------------------------- driver
def analyse_source(source: str, roots: frozenset[str] | None = None) -> ModuleFacts:
    tree = ast.parse(source)
    roots = product_roots() if roots is None else roots
    facts = ModuleFacts()
    if not has_guards_declaration(tree):
        facts.add("guards_declaration", 1)
    ps1_lines = ps1_text_asserts(tree)
    if ps1_lines and not module_runs_powershell(tree):
        for line in ps1_lines:
            facts.add("ps1_substring_without_execution", line)
    for line in private_src_imports(tree, roots):
        facts.add("private_src_import", line)
    for line in unmarked_spawning_tests(tree):
        facts.add("unmarked_spawning_test", line)
    facts.raises_match = raises_with_match(tree)
    return facts


def test_modules(tests_root: Path = TESTS_ROOT) -> list[Path]:
    found = [
        p
        for p in tests_root.rglob("*.py")
        if (p.name.startswith("test_") or p.name.endswith("_test.py")) and "__pycache__" not in p.parts
    ]
    return sorted(found, key=lambda p: p.as_posix())


def scan(repo_root: Path = REPO_ROOT) -> dict[str, ModuleFacts]:
    roots = product_roots(repo_root)
    result = {}
    for path in test_modules(repo_root / "tests"):
        rel = path.relative_to(repo_root).as_posix()
        result[rel] = analyse_source(path.read_text(encoding="utf-8"), roots)
    return result


def counts_by_rule(facts: dict[str, ModuleFacts]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {rule: {} for rule in RULES}
    for rel, module in facts.items():
        for rule, count in module.counts.items():
            if count:
                out[rule][rel] = count
    return {rule: dict(sorted(entries.items())) for rule, entries in out.items()}


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, dict[str, int]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != BASELINE_SCHEMA:
        raise ValueError(f"{path}: schema must be {BASELINE_SCHEMA!r}")
    rules = data.get("rules")
    if not isinstance(rules, dict) or set(rules) != set(RULES):
        raise ValueError(f"{path}: 'rules' must name exactly {sorted(RULES)}")
    for rule, entries in rules.items():
        if not isinstance(entries, dict):
            raise ValueError(f"{path}: rules.{rule} must be an object")
        for rel, count in entries.items():
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                raise ValueError(f"{path}: rules.{rule}[{rel!r}] must be a positive integer")
    return rules


def growth(current: dict[str, dict[str, int]], baseline: dict[str, dict[str, int]]) -> dict[str, list[str]]:
    """Per rule, the modules whose count exceeds the baseline allowance (missing entry = 0)."""
    failures: dict[str, list[str]] = {rule: [] for rule in RULES}
    for rule in RULES:
        allowed = baseline.get(rule, {})
        for rel, count in current.get(rule, {}).items():
            limit = allowed.get(rel, 0)
            if count > limit:
                failures[rule].append(f"{rel}: {count} > allowed {limit}")
    return failures


def tightened(current: dict[str, dict[str, int]], baseline: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for rule in RULES:
        now = current.get(rule, {})
        out[rule] = {
            rel: min(limit, now[rel]) for rel, limit in sorted(baseline.get(rule, {}).items()) if now.get(rel, 0) > 0
        }
    return out


def dump_baseline(rules: dict[str, dict[str, int]], path: Path = BASELINE_PATH) -> None:
    payload = {
        "schema": BASELINE_SCHEMA,
        "note": (
            "Allowances for tests/hygiene_ratchet.py. Counts may only go down; regenerate with "
            "'python -m tests.hygiene_ratchet --tighten'. Raising an entry needs owner approval."
        ),
        "rules": {rule: dict(sorted(rules.get(rule, {}).items())) for rule in RULES},
    }
    path.write_text(json.dumps(payload, indent=1, sort_keys=False) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--report", action="store_true", help="print counts and the growth check (default)")
    mode.add_argument("--tighten", action="store_true", help="lower baseline entries to today's counts")
    mode.add_argument("--write-baseline", action="store_true", help="reset the baseline to today's counts")
    args = parser.parse_args(argv)
    facts = scan()
    current = counts_by_rule(facts)
    if args.write_baseline:
        dump_baseline(current)
        print(f"wrote {BASELINE_PATH}")
        return 0
    baseline = load_baseline()
    if args.tighten:
        dump_baseline(tightened(current, baseline))
        print(f"tightened {BASELINE_PATH}")
        return 0
    for rule in RULES:
        entries = current[rule]
        print(f"{rule}: {sum(entries.values())} in {len(entries)} modules "
              f"(baseline {sum(baseline[rule].values())} in {len(baseline[rule])})")
    print(f"raises_match (guideline only): {sum(f.raises_match for f in facts.values())} "
          f"in {sum(1 for f in facts.values() if f.raises_match)} modules")
    failures = growth(current, baseline)
    bad = False
    for rule, lines in failures.items():
        for line in lines:
            bad = True
            print(f"GROWTH {rule}: {line} -- {RULE_HELP[rule]}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
