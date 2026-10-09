"""Structural ratchet: every path from a public entry point to a capture reader passes the panel gate first.

Guards: owner decision 3 (Swarm M 2026-10-06), U6 Defender M2/N1 and master-agent's fix-round item -- no CLI,
``__main__`` block, argparse handler or research runner may open 88a capture for a day without first calling
``maker_core.replay.export_gate.export_permitted`` (or its read alias ``read_permitted``).

The check is AST-level over every module under ``src/`` and ``tools/``, so a new module is covered automatically:

- **Readers** are the capture-opening primitives ``Reader``, ``Segment``, ``sealed_segments`` (maker_plugin_capture),
  ``ExportReader`` (maker_replay_bundle) and ``CaptureIndex`` (maker_plugin_runner), resolved through ``from``
  imports, ``as`` aliases and module aliases. Classes that subclass a reader are readers too.
- A function **reads** if it references a reader, or references (calls, passes or dispatches) a function that reads
  and is not gated. References include import aliases, so ``from m import export as e`` is followed.
- A function is **gated** only if it has no decorators and its first statement (after a docstring) calls the gate,
  imported from ``maker_core.replay.export_gate``, with the function's first parameter (or an attribute of it) as
  the day.
- **Rule:** a reading function that is not gated must have callers, all of which are then checked in turn, and must
  not be module-level code or a ``main``. So every root of a path to a reader is gated.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCAN = ("src", "tools")
READERS = frozenset({
    ("weather.market.maker_plugin_capture", "Reader"),
    ("weather.market.maker_plugin_capture", "Segment"),
    ("weather.market.maker_plugin_capture", "sealed_segments"),
    ("weather.market.maker_replay_bundle", "ExportReader"),
    ("weather.market.maker_plugin_runner", "CaptureIndex"),
})
GATES = frozenset({("maker_core.replay.export_gate", "export_permitted"),
                   ("maker_core.replay.export_gate", "read_permitted")})
# Entry points that must be gated today (the structural rule finds any new one by itself).
EXPECTED_GATED = frozenset({
    ("weather.market.maker_replay_night", "export_day"),
    ("weather.market.maker_replay_night_v02", "export_day"),
    ("weather.market.maker_replay_bundle", "export"),
    ("weather.market.maker_replay_bundle_v02", "export"),
    ("weather.market.maker_plugin_runner", "run"),
})


@dataclass
class Function:
    module: str
    name: str
    node: ast.AST | None  # None for module-level code
    refs: set = field(default_factory=set)


def module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[0] == "src":
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def sources(extra=None, replace=None):
    found = {}
    for folder in SCAN:
        for path in sorted((ROOT / folder).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            found[module_name(path)] = path.read_text(encoding="utf-8")
    found.update(replace or {})
    found.update(extra or {})
    return found


_PARSED: dict = {}


def _parse(name, text):
    key = (name, hash(text))
    if key not in _PARSED:
        _PARSED[key] = ast.parse(text)
    return _PARSED[key]


def _resolve_relative(module, level, target, is_package):
    base = module.split(".")
    base = base if is_package else base[:-1]
    if level > 1:
        base = base[:len(base) - (level - 1)]
    return ".".join([*base, target] if target else base)


class Analysis:
    def __init__(self, texts):
        self.modules = set(texts)
        self.functions: dict[tuple, Function] = {}
        self.aliases: dict[str, dict[str, tuple]] = {}
        self.module_aliases: dict[str, dict[str, str]] = {}
        self.reader_classes = set(READERS)
        self.trees = {name: _parse(name, text) for name, text in texts.items()}
        for name, tree in self.trees.items():
            self._imports(name, tree)
        self._reader_subclasses()
        for name, tree in self.trees.items():
            self._collect(name, tree)

    # ------------------------------------------------------------------ names
    def _imports(self, module, tree):
        names, mods = {}, {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                source = node.module or ""
                if node.level:
                    source = _resolve_relative(module, node.level, node.module, False)
                for alias in node.names:
                    local = alias.asname or alias.name
                    if f"{source}.{alias.name}" in self.modules:
                        mods[local] = f"{source}.{alias.name}"
                    names[local] = (source, alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        mods[alias.asname] = alias.name
                    else:
                        mods[alias.name.split(".")[0]] = alias.name.split(".")[0]
        self.aliases[module], self.module_aliases[module] = names, mods

    def resolve(self, module, expr):
        """The (module, name) an expression refers to, or None."""
        if isinstance(expr, ast.Name):
            if expr.id in self.aliases[module]:
                return self.aliases[module][expr.id]
            return (module, expr.id)
        if isinstance(expr, ast.Attribute):
            parts = []
            node = expr
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value
            if not isinstance(node, ast.Name):
                return None
            parts.reverse()
            head = node.id
            base = self.module_aliases[module].get(head)
            if base is None:
                return None
            dotted = [base, *parts]
            for cut in range(len(dotted) - 1, 0, -1):
                candidate = ".".join(dotted[:cut])
                if candidate in self.modules or cut == 1:
                    return (candidate, dotted[cut])
        return None

    def canonical(self, target):
        """Follow re-exports: a name imported into a module refers to its source definition."""
        seen = set()
        while target and target not in seen:
            seen.add(target)
            module, name = target
            if module in self.aliases and name in self.aliases[module] and (module, name) not in self.functions:
                target = self.aliases[module][name]
                continue
            break
        return target

    def _reader_subclasses(self):
        changed = True
        while changed:
            changed = False
            for module, tree in self.trees.items():
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef) and (module, node.name) not in self.reader_classes:
                        if any(self.canonical(self.resolve(module, base)) in self.reader_classes for base in node.bases):
                            self.reader_classes.add((module, node.name))
                            changed = True

    # -------------------------------------------------------------- functions
    def _collect(self, module, tree):
        top = Function(module, "<module>", None)
        self.functions[(module, "<module>")] = top

        def nested_defs(node):
            """Function and class definitions inside a compound statement, without entering any definition."""
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    yield child
                elif not isinstance(child, ast.Lambda):
                    yield from nested_defs(child)

        def visit(body, owner, prefix, in_reader_class):
            for stmt in body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = prefix + stmt.name
                    fn = Function(module, name, stmt)
                    if not in_reader_class:
                        self.functions[(module, name)] = fn
                    for deco in stmt.decorator_list:
                        self._refs(module, deco, owner)
                    visit(stmt.body, fn, name + ".", in_reader_class)
                elif isinstance(stmt, ast.ClassDef):
                    # Bases are type references, not reads: a subclass of a reader is itself a reader class.
                    reader = (module, stmt.name) in self.reader_classes
                    visit(stmt.body, owner, prefix + stmt.name + ".", in_reader_class or reader)
                else:
                    self._refs(module, stmt, owner)
                    visit(list(nested_defs(stmt)), owner, prefix, in_reader_class)

        visit(tree.body, top, "", False)

    def _refs(self, module, node, owner):
        stack = [node]
        while stack:
            current = stack.pop()
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and current is not node:
                continue
            if isinstance(current, (ast.Name, ast.Attribute)) and isinstance(getattr(current, "ctx", None), ast.Load):
                target = self.resolve(module, current)
                if target is not None:
                    owner.refs.add(target)
                if isinstance(current, ast.Attribute):
                    continue  # the chain is resolved as a whole
            stack.extend(ast.iter_child_nodes(current))

    # ------------------------------------------------------------------ rule
    def gated(self, fn):
        node = fn.node
        if node is None or node.decorator_list:
            return False
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        if not body or not isinstance(body[0], ast.Expr) or not isinstance(body[0].value, ast.Call):
            return False
        call = body[0].value
        if self.canonical(self.resolve(fn.module, call.func)) not in GATES or not call.args:
            return False
        params = [a.arg for a in (*node.args.posonlyargs, *node.args.args)]
        if not params:
            return False
        day = call.args[0]
        base = day.value if isinstance(day, ast.Attribute) else day
        return isinstance(base, ast.Name) and base.id == params[0]

    def reading(self):
        reads = set()
        changed = True
        while changed:
            changed = False
            for key, fn in self.functions.items():
                if key in reads:
                    continue
                for ref in fn.refs:
                    target = self.canonical(ref)
                    if target in self.reader_classes or (
                            target in reads and not self.gated(self.functions[target])):
                        reads.add(key)
                        changed = True
                        break
        return reads

    def violations(self):
        reads = self.reading()
        callers = {key: set() for key in self.functions}
        for key, fn in self.functions.items():
            for ref in fn.refs:
                target = self.canonical(ref)
                if target in callers and target != key:
                    callers[target].add(key)
        problems = []
        for key in sorted(reads):
            fn = self.functions[key]
            if self.gated(fn):
                continue
            if fn.node is None:
                problems.append(f"{key[0]}: module-level code opens capture without the gate")
            elif fn.name.split(".")[-1] == "main":
                problems.append(f"{key[0]}.{fn.name}: a main opens capture without the gate")
            elif not callers[key]:
                problems.append(f"{key[0]}.{fn.name}: opens capture, is not gated and has no gated caller")
        return problems

    def gated_entry_points(self):
        reads = self.reading()
        return {key for key in reads if self.gated(self.functions[key])}


@pytest.fixture(scope="module")
def baseline():
    return sources()


def test_every_path_to_a_capture_reader_is_gated(baseline):
    analysis = Analysis(baseline)
    assert analysis.violations() == []
    assert EXPECTED_GATED <= analysis.gated_entry_points()


def test_the_scan_sees_the_known_readers_and_their_callers(baseline):
    analysis = Analysis(baseline)
    reads = analysis.reading()
    for key in [("weather.market.maker_plugin_runner", "process"), ("weather.market.maker_replay_night", "_inventory"),
                ("weather.market.maker_replay_bundle_v02", "_project"), *EXPECTED_GATED]:
        assert key in reads, key
    assert ("weather.market.maker_replay_bundle", "ExportReader") in analysis.reader_classes


FAKE_CLI = '''
import argparse
from weather.market.maker_plugin_capture import Reader as CaptureReader


def main(argv=None):
    args = argparse.ArgumentParser().parse_args(argv)
    return CaptureReader(args.root, 60, 1024)


if __name__ == "__main__":
    raise SystemExit(main())
'''


@pytest.mark.parametrize("name, source", [
    ("fake_cli_alias", FAKE_CLI),
    ("fake_cli_module_alias", "import weather.market.maker_replay_bundle as b\n\ndef main(argv=None):\n"
                              "    return b.ExportReader(argv, 1, 1)\n"),
    ("fake_cli_module_level", "from weather.market.maker_plugin_capture import sealed_segments\n"
                              "rows = list(sealed_segments(None, '2026-10-01'))\n"),
    ("fake_cli_via_helper", "from weather.market.maker_plugin_runner import process as p\n\n"
                            "def go(args):\n    return p(None, None, None, args.date, set(), None)\n"),
    ("fake_cli_subclass", "from weather.market.maker_plugin_capture import Reader\n\nclass Mine(Reader):\n"
                          "    pass\n\ndef handler(args):\n    return Mine(args.root, 1, 1)\n"),
    ("fake_cli_decorated_gate", "import functools\nfrom maker_core.replay.export_gate import export_permitted\n"
                                "from weather.market.maker_plugin_capture import Reader\n\n@functools.lru_cache\n"
                                "def run(args):\n    export_permitted(args.date)\n    return Reader(args.root, 1, 1)\n"),
    ("fake_cli_local_gate", "from weather.market.maker_plugin_capture import Reader\n\n"
                            "def export_permitted(day):\n    return day\n\ndef run(args):\n"
                            "    export_permitted(args.date)\n    return Reader(args.root, 1, 1)\n"),
    ("fake_cli_gate_wrong_day", "from maker_core.replay.export_gate import export_permitted\n"
                                "from weather.market.maker_plugin_capture import Reader\nOTHER = '2026-09-01'\n\n"
                                "def run(args):\n    export_permitted(OTHER)\n    return Reader(args.root, 1, 1)\n"),
])
def test_mutant_new_module_reading_capture_without_the_gate_fails(baseline, name, source):
    mutant = Analysis(sources(extra={f"tools.research.{name}": source}))
    assert mutant.violations(), name


def test_a_properly_gated_new_module_passes(baseline):
    good = ("from maker_core.replay.export_gate import read_permitted as gate\n"
            "from weather.market.maker_plugin_capture import Reader\n\n"
            "def run(args):\n    \"\"\"Doc.\"\"\"\n    gate(args.date)\n    return Reader(args.root, 1, 1)\n\n"
            "def main(argv=None):\n    return run(argv)\n")
    assert Analysis(sources(extra={"tools.research.fake_ok": good})).violations() == []


@pytest.mark.parametrize("module, line", [
    ("weather.market.maker_replay_night",
     '    export_permitted(args.day, getattr(args, "owner_decision", None))  # first: before any input\n'),
    ("weather.market.maker_replay_night_v02",
     '    export_permitted(args.day, getattr(args, "owner_decision", None))  # first: before any input\n'),
    ("weather.market.maker_replay_bundle",
     '    export_permitted(args.date, getattr(args, "owner_decision", None))  # first: before any input\n'),
    ("weather.market.maker_replay_bundle_v02",
     '    export_permitted(args.date, getattr(args, "owner_decision", None))  # first: before any input\n'),
    ("weather.market.maker_plugin_runner",
     '    read_permitted(args.date, getattr(args, "owner_decision", None))  # first: before any input\n'),
])
@pytest.mark.parametrize("mutation", ["remove", "move_down"])
def test_mutant_removing_or_moving_the_gate_in_any_entry_point_fails(baseline, module, line, mutation):
    text = baseline[module]
    assert text.count(line) == 1
    if mutation == "remove":
        mutated = text.replace(line, "")
    else:  # the gate is no longer the first statement
        mutated = text.replace(line, "    _ = None\n" + line)
    assert Analysis(sources(replace={module: mutated})).violations(), (module, mutation)
