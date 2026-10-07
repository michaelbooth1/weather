"""Select the test files a change can affect, from the static import and file-reference graph.

Usage: ``python -m weather.operations.affected_tests --base origin/master [--head HEAD | --worktree]``.

The graph is built from the tracked tree of a git revision (or the working tree). Edges:

- **code** - an ``import`` (module level) adds an edge to the module and every parent package
  ``__init__``; in tests and scripts, a string naming a known module (``monkeypatch.setattr``
  targets, ``python -m`` arguments) does too; a PowerShell line that runs ``-m weather.x`` or
  names a ``.ps1``/``.py`` file it launches or dot-sources (PowerShell is text-scanned).
- **lazy** - an import inside a product function body (it runs only when that function is called).
- **data** - a string constant, a ``Path / "a" / "b"`` chain or the constant arguments of a call
  such as ``repo_path("scripts", "ops", "x.ps1")`` that names a tracked file; in a test file, a
  tracked directory (two or more components) whose files the test does not name one by one; a
  module name a PowerShell script only mentions (an allowlist entry).

A test file is selected when it changed or reaches a changed file. A chain crosses at most one
data edge; a data or lazy edge from product code reaches only tests within
``PRODUCT_DATA_REACH`` import hops of the referring module; a test file passes a change on only
to tests that import it. pytest configuration, any ``conftest.py``, dependency pins and the
import bootstrap select the full suite. The repository ratchets are always selected. The result
is advisory: CI's full suite remains the merge evidence (see docs/development.md).
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
import subprocess
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Mapping

from weather.paths import REPO_ROOT

PYTHON_ROOTS = ("src/", "app/", "tests/", "scripts/", "tools/", "weather/")
TEXT_SCAN_SUFFIXES = (".ps1", ".psm1", ".cmd", ".bat")
# Changes here alter collection, the interpreter environment or every import.
FULL_SUITE_PATHS = frozenset(
    {
        "pytest.ini",
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
        "tox.ini",
        "sitecustomize.py",
        "weather/__init__.py",
        "src/__init__.py",
        "tests/__init__.py",
    }
)  # plus any conftest.py and requirements*.txt
# Repository-wide ratchets and inventories: cheap, and they are what fires most often.
ALWAYS_RUN_TESTS = (
    "tests/operations/test_schema_registry.py",
    "tests/operations/test_import_architecture.py",
    "tests/operations/test_path_policy.py",
    "tests/operations/test_module_size_audit.py",
    "tests/operations/test_agent_docs_audit.py",
    "tests/operations/test_ops_script_ratchets.py",
    "tests/operations/test_repo_health_ratchets.py",
    "tests/operations/test_research_harness.py",
    "tests/operations/test_knowledge_structure_audit.py",
    "tests/operations/test_config_inventory.py",
    "tests/operations/test_structure_inventory.py",
)
ALWAYS_RUN_COMMANDS = (
    "python -m compileall -q app src tests",
    "python -m weather.operations.agent_docs_audit",
    "python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check",
)
# A file named by product code (a module that reads a config file, hashes a script or
# launches it), or imported inside a product function, reaches tests at most this many
# import hops from the referring module.
PRODUCT_DATA_REACH = 2
_UNBOUNDED = 1_000_000
# Basenames this common are not evidence of a reference to one particular file.
AMBIGUOUS_BASENAME_LIMIT = 5
_MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
_PS_MODULE = re.compile(r"\b(weather(?:\.[A-Za-z_][A-Za-z0-9_]*)+)")
_PS_RUNS = re.compile(r"(?:^|[\s'\"(,])-m\b|run_module|\$module\s*=", re.IGNORECASE)
_PS_FILE = re.compile(r"([A-Za-z0-9_.\-]+\.(?:ps1|psm1|py|json|ya?ml|toml|txt|csv|md))\b", re.IGNORECASE)


# --------------------------------------------------------------------------- tree access


@dataclass
class Tree:
    """A set of tracked paths and a reader for their bytes."""

    paths: list[str]
    read: Callable[[Iterable[str]], dict[str, bytes]]


def _git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.decode('utf-8', 'replace').strip()}")
    return completed.stdout


def git_tree(repo: Path, rev: str) -> Tree:
    """The tracked tree of ``rev``, read from the object store (no checkout needed)."""

    raw = _git(repo, "ls-tree", "-r", "-z", "--name-only", rev)
    paths = [p for p in raw.decode("utf-8").split("\0") if p]

    def read(wanted: Iterable[str]) -> dict[str, bytes]:
        wanted = list(wanted)
        if not wanted:
            return {}
        request = "".join(f"{rev}:{p}\n" for p in wanted).encode("utf-8")
        out = _git(repo, "cat-file", "--batch", input_bytes=request)
        result: dict[str, bytes] = {}
        pos = 0
        for path in wanted:
            end = out.index(b"\n", pos)
            header = out[pos:end].split()
            pos = end + 1
            if len(header) < 3 or header[1] == b"missing":
                continue
            size = int(header[2])
            result[path] = out[pos : pos + size]
            pos += size + 1
        return result

    return Tree(paths=paths, read=read)


def work_tree(repo: Path) -> Tree:
    """Tracked plus untracked-but-not-ignored files of the working tree, read from disk."""

    raw = _git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    paths = sorted({p for p in raw.decode("utf-8").split("\0") if p and (repo / p).is_file()})

    def read(wanted: Iterable[str]) -> dict[str, bytes]:
        result = {}
        for path in wanted:
            try:
                result[path] = (repo / path).read_bytes()
            except OSError:
                continue
        return result

    return Tree(paths=paths, read=read)


def dict_tree(files: Mapping[str, str | bytes]) -> Tree:
    """An in-memory tree, for tests and for callers that already hold the bytes."""

    data = {k: v.encode("utf-8") if isinstance(v, str) else v for k, v in files.items()}
    return Tree(paths=sorted(data), read=lambda wanted: {p: data[p] for p in wanted if p in data})


def changed_files(repo: Path, base: str, head: str | None, *, merge_base: bool = True) -> list[str]:
    """Paths changed between ``base`` and ``head`` (``None`` = working tree). Renames list both sides."""

    if merge_base:
        base = _git(repo, "merge-base", base, head or "HEAD").decode().strip()
    args = ["diff", "--name-status", "-z", "-M", base]
    if head:
        args.append(head)
    fields = [f for f in _git(repo, *args).decode("utf-8").split("\0") if f]
    paths: set[str] = set()
    i = 0
    while i < len(fields):
        status = fields[i]
        width = 2 if status[:1] in {"R", "C"} else 1
        paths.update(fields[i + 1 : i + 1 + width])
        i += 1 + width
    if head is None:
        untracked = _git(repo, "ls-files", "-z", "--others", "--exclude-standard").decode("utf-8")
        paths.update(p for p in untracked.split("\0") if p)
    return sorted(paths)


# --------------------------------------------------------------------------- graph


def module_name(path: str) -> str | None:
    """The importable dotted name of a Python path, or ``None``."""

    if not path.endswith(".py"):
        return None
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts[0] == "src":
        parts = parts[1:]
    if not parts:
        return None
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts or not all(p.isidentifier() for p in parts):
        return None
    return ".".join(parts)


def is_test_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return path.startswith("tests/") and name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def is_full_suite_trigger(path: str) -> bool:
    name = PurePosixPath(path).name
    return path in FULL_SUITE_PATHS or name == "conftest.py" or fnmatch.fnmatch(path, "requirements*.txt")


@dataclass
class FileRefs:
    """Outgoing references of one file, before resolution."""

    modules: set[str] = field(default_factory=set)
    # Module names a script only mentions (allowlists, messages), not runs.
    mentioned_modules: set[str] = field(default_factory=set)
    # Imports inside a function body run only when that function is called.
    lazy_modules: set[str] = field(default_factory=set)
    strings: set[str] = field(default_factory=set)
    parse_error: str | None = None


def _string_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _division_parts(node: ast.AST) -> list[str]:
    """String constants of a ``a / "b" / "c"`` chain, in order."""

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _division_parts(node.left) + _division_parts(node.right)
    value = _string_value(node)
    if value is not None:
        return [value]
    if isinstance(node, ast.Call):
        return [s for s in (_string_value(a) for a in node.args) if s is not None]
    return []


def _relative_base(path: str, level: int) -> str:
    name = module_name(path) or ""
    parts = name.split(".") if name else []
    if not PurePosixPath(path).name == "__init__.py":
        parts = parts[:-1]
    if level > 1:
        parts = parts[: len(parts) - (level - 1)]
    return ".".join(parts)


def python_refs(path: str, source: bytes) -> FileRefs:
    refs = FileRefs()
    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError) as exc:
        refs.parse_error = f"{type(exc).__name__}: {exc}"
        return refs
    # One pass: (node, inside a function body, is the left operand of a "/" chain).
    stack: list[tuple[ast.AST, bool, bool]] = [(tree, False, False)]
    while stack:
        node, in_function, inner_division = stack.pop()
        child_in_function = in_function or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
        is_division = isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
        for child in ast.iter_child_nodes(node):
            stack.append((child, child_in_function, is_division and child is node.left))
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names: set[str] = set()
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            else:
                base = node.module or ""
                if node.level:
                    prefix = _relative_base(path, node.level)
                    base = f"{prefix}.{base}" if prefix and base else (prefix or base)
                if base:
                    names.add(base)
                    names.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
            (refs.lazy_modules if in_function else refs.modules).update(names)
        elif is_division and not inner_division:
            parts = _division_parts(node)
            if parts:
                refs.strings.add("/".join(parts))
        elif isinstance(node, ast.Call):
            parts = [s for s in (_string_value(a) for a in node.args) if s is not None]
            if len(parts) > 1:
                refs.strings.add("/".join(parts))
        value = _string_value(node)
        if value is not None and len(value) < 400 and "\n" not in value:
            refs.strings.add(value)
    refs.lazy_modules -= refs.modules
    return refs


def text_refs(source: bytes) -> FileRefs:
    """Text scan of a PowerShell or batch file (not Python code analysis)."""

    text = source.decode("utf-8", "replace")
    refs = FileRefs()
    previous = ""
    for line in text.splitlines():
        names = _PS_MODULE.findall(line)
        if names:
            runs = _PS_RUNS.search(line) or (_PS_RUNS.search(previous) and line.strip().startswith(("'", '"')))
            (refs.modules if runs else refs.mentioned_modules).update(names)
        previous = line
    refs.strings.update(_PS_FILE.findall(text))
    return refs


def _normalise(candidate: str) -> str:
    text = candidate.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/")


@dataclass
class Edge:
    target: str
    reason: str
    # "code": the source executes the target (import, python -m, a script it runs).
    # "data": the source names the target as a file or directory.
    kind: str = "code"


@dataclass
class Graph:
    paths: set[str]
    edges: dict[str, list[Edge]]
    parse_errors: dict[str, str]
    module_files: dict[str, list[str]]

    def dependents(self) -> dict[str, list[tuple[str, str, str]]]:
        reverse: dict[str, list[tuple[str, str, str]]] = {}
        for source, edges in self.edges.items():
            for edge in edges:
                reverse.setdefault(edge.target, []).append((source, edge.reason, edge.kind))
        return reverse


def build_graph(tree: Tree) -> Graph:
    paths = set(tree.paths)
    module_files: dict[str, list[str]] = {}
    for path in tree.paths:
        if path.endswith(".py") and (path.startswith(PYTHON_ROOTS) or "/" not in path):
            name = module_name(path)
            if name:
                module_files.setdefault(name, []).append(path)
    by_basename: dict[str, list[str]] = {}
    directories: dict[str, list[str]] = {}
    for path in tree.paths:
        by_basename.setdefault(PurePosixPath(path).name, []).append(path)
        parents = PurePosixPath(path).parents
        for parent in list(parents)[:-1]:
            directories.setdefault(parent.as_posix(), []).append(path)

    def module_targets(name: str) -> list[tuple[str, str]]:
        """Files executed by importing ``name``: the longest known module plus parent packages."""

        parts = name.split(".")
        found: list[tuple[str, str]] = []
        for i in range(len(parts), 0, -1):
            candidate = ".".join(parts[:i])
            for target in module_files.get(candidate, ()):
                found.append((target, candidate))
        return found

    dirs_by_suffix: dict[str, list[str]] = {}
    for directory in directories:
        parts = directory.split("/")
        for i in range(len(parts) - 1):
            dirs_by_suffix.setdefault("/".join(parts[i:]), []).append(directory)

    def resolve_string(text: str, *, allow_directories: bool) -> tuple[str, list[str], list[str]]:
        """(the matched form, the files it names, the directories it names)."""

        norm = _normalise(text)
        if not norm or len(norm) > 300 or " " in norm:
            return norm, [], []
        if norm in paths:
            return norm, [norm], []
        parts = norm.split("/")
        # Leading components may be a variable's value ("repo/scripts/ops"); keep two or more.
        for i in range(max(len(parts) - 1, 0)):
            candidate = "/".join(parts[i:])
            hits = [p for p in by_basename.get(parts[-1], ()) if p == candidate or p.endswith("/" + candidate)]
            if hits:
                return candidate, hits, []
            if allow_directories and candidate in dirs_by_suffix:
                found = dirs_by_suffix[candidate]
                return candidate, sorted({f for d in found for f in directories[d]}), found
        if len(parts) == 1 and "." in norm and not norm.startswith("."):
            hits = by_basename.get(norm, [])
            if 0 < len(hits) <= AMBIGUOUS_BASENAME_LIMIT:
                return norm, hits, []
        return norm, [], []

    python_files = _flat(module_files)
    wanted = [p for p in tree.paths if p in python_files or p.lower().endswith(TEXT_SCAN_SUFFIXES)]
    contents = tree.read(wanted)
    edges: dict[str, list[Edge]] = {}
    parse_errors: dict[str, str] = {}
    for path in wanted:
        source = contents.get(path)
        if source is None:
            continue
        refs = text_refs(source) if path.lower().endswith(TEXT_SCAN_SUFFIXES) else python_refs(path, source)
        if refs.parse_error:
            parse_errors[path] = refs.parse_error
        text_scanned = path.lower().endswith(TEXT_SCAN_SUFFIXES)
        out: dict[str, tuple[str, str]] = {}
        for name in sorted(refs.modules):
            for target, module in module_targets(name):
                out.setdefault(target, (f"{'runs' if text_scanned else 'imports'} {module}", "code"))
        lazy_kind = "code" if path.startswith("tests/") else "lazy"
        for name in sorted(refs.lazy_modules):
            for target, module in module_targets(name):
                out.setdefault(target, (f"imports {module} inside a function", lazy_kind))
        for name in sorted(refs.mentioned_modules):
            for target, module in module_targets(name):
                out.setdefault(target, (f"mentions module {module}", "data"))
        in_tests = path.startswith("tests/")
        directory_refs: list[tuple[str, list[str], list[str]]] = []
        # A module name in product code is usually data (registries, messages), not an import.
        follow_module_strings = not path.startswith(("src/", "app/", "weather/"))
        for text in sorted(refs.strings):
            if follow_module_strings and _MODULE_NAME.match(text):
                for target, module in module_targets(text):
                    out.setdefault(target, (f"names module {module}", "code"))
            matched, hits, found_dirs = resolve_string(text, allow_directories=in_tests)
            if found_dirs:
                directory_refs.append((matched, found_dirs, hits))
                continue
            for target in hits:
                if text_scanned and target.lower().endswith((".ps1", ".psm1", ".py")):
                    out.setdefault(target, (f"runs {matched}", "code"))
                else:
                    out.setdefault(target, (f"references {matched}", "data"))
        # A directory counts only when the file names nothing inside it: "ROOT / 'scripts' / 'ops'"
        # is usually the prefix of a specific script, while an inventory test lists the directory.
        for matched, found_dirs, members in directory_refs:
            if any(target.startswith(d + "/") for d in found_dirs for target in out):
                continue
            for target in members:
                out.setdefault(target, (f"references directory {matched}", "data"))
        out.pop(path, None)
        edges[path] = [Edge(target, reason, kind) for target, (reason, kind) in sorted(out.items())]
    return Graph(paths=paths, edges=edges, parse_errors=parse_errors, module_files=module_files)


def _flat(module_files: Mapping[str, list[str]]) -> set[str]:
    return {p for files in module_files.values() for p in files}


# --------------------------------------------------------------------------- selection


@dataclass
class Selection:
    changed: list[str]
    full_suite: bool
    full_suite_reasons: list[str]
    tests: dict[str, str]
    commands: list[str]
    unreferenced_changes: list[str]
    parse_errors: dict[str, str]
    suite_files: int = 0

    def as_dict(self) -> dict:
        return {
            "suite_test_files": self.suite_files,
            "changed": self.changed,
            "full_suite": self.full_suite,
            "full_suite_reasons": self.full_suite_reasons,
            "tests": [{"file": f, "reason": r} for f, r in sorted(self.tests.items())],
            "always_run_commands": self.commands,
            "changes_without_test_reach": self.unreferenced_changes,
            "parse_errors": self.parse_errors,
        }


def select(graph: Graph, changed: Iterable[str]) -> Selection:
    """Tests that are changed or reach a changed file; each reason is a shortest path."""

    changed = sorted(set(changed))
    triggers = [p for p in changed if is_full_suite_trigger(p)]
    reverse = graph.dependents()
    tests: dict[str, str] = {}
    for test in ALWAYS_RUN_TESTS:
        if test in graph.paths:
            tests[test] = "always run: repository ratchet"
    unreferenced: list[str] = []
    for start in changed:
        if is_test_file(start) and start in graph.paths:
            tests[start] = "changed test file"
        # A chain may cross at most one data edge: "config.json <- loader.py <- importers" and
        # "module <- script.ps1 <- test that runs it" are real; data edges chained through
        # code ("doc <- script that mentions it <- module that names the script") are not.
        # A test file is a leaf unless another test imports it.
        # State: (file, data edges used, code hops still allowed after a product data edge).
        start_state = (start, 0, _UNBOUNDED)
        parent: dict[tuple[str, int, int], tuple[tuple[str, int, int], str] | None] = {start_state: None}
        best: dict[str, list[tuple[int, int]]] = {start: [(0, start_state[2])]}
        queue = deque([start_state])
        reached = False
        while queue:
            state = queue.popleft()
            node, data_used, budget = state
            for source, reason, kind in reverse.get(node, ()):
                if is_test_file(node) and not (is_test_file(source) and kind == "code"):
                    continue
                if kind == "data":
                    used = data_used + 1
                    product = not source.startswith(("tests/", "scripts/", "tools/"))
                    remaining = min(budget, PRODUCT_DATA_REACH) if product else budget
                elif kind == "lazy":
                    used, remaining = data_used, min(budget, PRODUCT_DATA_REACH)
                else:
                    used, remaining = data_used, budget - 1
                if used > 1 or remaining < 0:
                    continue
                if any(u <= used and r >= remaining for u, r in best.get(source, ())):
                    continue
                best.setdefault(source, []).append((used, remaining))
                next_state = (source, used, remaining)
                parent[next_state] = (state, reason)
                queue.append(next_state)
                if is_test_file(source):
                    reached = True
                    if source not in tests or tests[source].startswith("always run"):
                        tests[source] = _explain(parent, next_state, start)
        if not reached and not is_test_file(start):
            unreferenced.append(start)
    if triggers:
        for path in graph.paths:
            if is_test_file(path):
                tests.setdefault(path, "full suite: " + ", ".join(triggers))
    return Selection(
        changed=changed,
        full_suite=bool(triggers),
        full_suite_reasons=triggers,
        tests=tests,
        commands=list(ALWAYS_RUN_COMMANDS),
        unreferenced_changes=unreferenced,
        parse_errors=dict(graph.parse_errors),
        suite_files=sum(1 for path in graph.paths if is_test_file(path)),
    )


def _explain(parent: Mapping, state: tuple, changed: str) -> str:
    steps: list[str] = []
    hop = parent.get(state)
    while hop is not None:
        previous, reason = hop
        steps.append(f"{state[0]} {reason}")
        state = previous
        hop = parent.get(state)
    return f"{changed} changed: " + " -> ".join(steps)


def add_deleted_module_edges(graph: Graph, tree: Tree, changed: Iterable[str]) -> None:
    """Link files that still import a module whose file the change deleted or renamed away."""

    missing = {module_name(p): p for p in changed if p not in graph.paths and module_name(p)}
    if not missing:
        return
    contents = tree.read(sorted(p for p in graph.edges if p.endswith(".py")))
    for path, source in contents.items():
        refs = python_refs(path, source)
        names = refs.modules | {s for s in refs.strings if _MODULE_NAME.match(s)}
        for name in names:
            for module, deleted in missing.items():
                if name == module or name.startswith(module + "."):
                    graph.edges.setdefault(path, []).append(Edge(deleted, f"imports {module} (removed)"))


def affected_tests(repo: Path, base: str, head: str | None = "HEAD", *, merge_base: bool = True) -> Selection:
    tree = git_tree(repo, head) if head else work_tree(repo)
    changed = changed_files(repo, base, head, merge_base=merge_base)
    graph = build_graph(tree)
    add_deleted_module_edges(graph, tree, changed)
    return select(graph, changed)


# --------------------------------------------------------------------------- CLI


def render_text(selection: Selection) -> str:
    lines = [f"changed files: {len(selection.changed)}"]
    if selection.full_suite:
        lines.append("FULL SUITE: " + ", ".join(selection.full_suite_reasons))
    lines.append(f"selected test files: {len(selection.tests)} of {selection.suite_files}")
    for test, reason in sorted(selection.tests.items()):
        lines.append(f"  {test}")
        lines.append(f"      why: {reason}")
    if selection.unreferenced_changes:
        lines.append("changes no test reaches statically (rely on the ratchets and CI's full suite):")
        lines.extend(f"  {p}" for p in selection.unreferenced_changes)
    if selection.parse_errors:
        lines.append("files that did not parse (their imports are unknown):")
        lines.extend(f"  {p}: {e}" for p, e in sorted(selection.parse_errors.items()))
    lines.append("always run:")
    lines.extend(f"  {c}" for c in selection.commands)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/master", help="base revision (default origin/master)")
    parser.add_argument("--head", default="HEAD", help="head revision (default HEAD)")
    parser.add_argument("--worktree", action="store_true", help="use the working tree, including uncommitted and untracked files, as head")
    parser.add_argument("--no-merge-base", action="store_true", help="diff base..head directly instead of from their merge base")
    parser.add_argument("--repo", default=str(REPO_ROOT), help="repository root (default: this checkout)")
    parser.add_argument("--format", choices=("text", "json", "paths"), default="text", help="paths prints only the test files, space separated, for pytest")
    args = parser.parse_args(argv)
    repo = Path(args.repo)
    head = None if args.worktree else args.head
    selection = affected_tests(repo, args.base, head, merge_base=not args.no_merge_base)
    if args.format == "json":
        print(json.dumps(selection.as_dict(), indent=2, sort_keys=True))
    elif args.format == "paths":
        print(" ".join(sorted(selection.tests)))
    else:
        print(render_text(selection))
    return 0


if __name__ == "__main__":
    sys.exit(main())
