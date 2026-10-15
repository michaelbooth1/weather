"""Landing preflight roll-class engine (L-P4): static import graph and the F9/F13 classifier.

Ported from the Swarm L L-R3 classifier (stdlib only).  A PREDICTION, never
binding: the capture host's ``scripts/ops/roll_verdict.ps1`` decides from the
live ``source_scope_files`` closures.  The class is predicted from

1. a dated closure snapshot (the union of the live closures relayed from
   production), when one is supplied;
2. a static import graph walked from the loop entry modules on the tree before
   the head lands and on the landing tree (execution-tape entries included by
   default); the graph is built from source text, nothing is imported;
3. the schema-registry family rule: ``src/weather/schema_registry*.py`` is
   always sensitive.

Candidates are chosen exactly as roll_verdict chooses them: changed ``*.py``
under ``src/`` or ``weather/`` and not under ``tests/``.  Classes (F9/F13):

* EXPECTED-ROLL-SENSITIVE: a candidate is in the snapshot, reached by the static
  graph, or in the schema family;
* EXPECTED-UNDECIDABLE ("schedule as roll-sensitive"): nothing is sensitive but
  the supplied snapshot is older than ``SNAPSHOT_MAX_AGE_DAYS`` (or unreadable)
  while importable files changed, or a changed importable file is in neither
  the snapshot nor the static graph's module index, or the walk could not parse
  a reached module;
* EXPECTED-ROLL-FREE otherwise.

Module naming mirrors how the capture loops resolve imports on the host:
``src/<pkg>/.../<mod>.py`` is ``<pkg>....<mod>``; the repo-root shim
``weather/__init__.py`` *is* the ``weather`` package, so ``src/weather/__init__.py``
is shadowed and never executed by a loop.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from weather.operations.landing_preflight_rollclass_schema import (
    SchemaAdditiveResult,
    classify_schema_change,
    is_schema_family,
)

EDGE_MODULE = "module"  # executed at import time (module body, class body, try/if at top level)
EDGE_DEFERRED = "deferred"  # inside a function or lambda body: executed only when called

ROOT_SHIM_PATH = "weather/__init__.py"
SHADOWED_SRC_INIT = "src/weather/__init__.py"

Reader = Callable[[str], bytes]


@dataclass(frozen=True)
class ImportRef:
    """One import statement target, already made absolute."""

    target: str
    kind: str
    lineno: int
    from_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedModule:
    imports: tuple[ImportRef, ...]
    dynamic_import_lines: tuple[int, ...]
    parse_error: str | None = None


def module_name_for_path(path: str) -> str | None:
    """Return the dotted module a repo path is imported as, or None if not importable."""

    if not path.endswith(".py"):
        return None
    if path == ROOT_SHIM_PATH:
        return "weather"
    if not path.startswith("src/"):
        return None
    parts = path[len("src/") : -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return None  # src/__init__.py
    if not all(part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


def _is_type_checking_test(node: ast.expr) -> bool:
    if isinstance(node, ast.Name) and node.id == "TYPE_CHECKING":
        return True
    return isinstance(node, ast.Attribute) and node.attr == "TYPE_CHECKING"


def _resolve_relative(module: str, is_package: bool, level: int, name: str | None) -> str | None:
    package_parts = module.split(".") if is_package else module.split(".")[:-1]
    if level - 1 > len(package_parts):
        return None
    base_parts = package_parts[: len(package_parts) - (level - 1)]
    if name:
        base_parts = base_parts + name.split(".")
    return ".".join(base_parts) if base_parts else None


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self, module: str, is_package: bool) -> None:
        self.module = module
        self.is_package = is_package
        self.depth = 0
        self.imports: list[ImportRef] = []
        self.dynamic: list[int] = []

    def _kind(self) -> str:
        return EDGE_DEFERRED if self.depth else EDGE_MODULE

    def _function(self, node: ast.AST) -> None:
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function
    visit_Lambda = _function

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking_test(node.test):
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(ImportRef(alias.name, self._kind(), node.lineno))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            target = _resolve_relative(self.module, self.is_package, node.level, node.module)
        else:
            target = node.module
        if target:
            names = tuple(alias.name for alias in node.names if alias.name != "*")
            self.imports.append(ImportRef(target, self._kind(), node.lineno, names))

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
        if name in ("import_module", "__import__") and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and not first.value.startswith("."):
                self.imports.append(ImportRef(first.value, self._kind(), node.lineno))
            else:
                self.dynamic.append(node.lineno)
        self.generic_visit(node)


def parse_module(source: bytes, module: str, is_package: bool) -> ParsedModule:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return ParsedModule((), (), parse_error=f"{type(exc).__name__}: {exc}")
    visitor = _ImportVisitor(module, is_package)
    visitor.visit(tree)
    return ParsedModule(tuple(visitor.imports), tuple(visitor.dynamic))


@dataclass
class ParseCache:
    """Parse results keyed by (content key, module, is_package); share it across trees."""

    entries: dict[tuple[str, str, bool], ParsedModule] = field(default_factory=dict)

    def get(self, key: str, module: str, is_package: bool, reader: Reader) -> ParsedModule:
        cache_key = (key, module, is_package)
        hit = self.entries.get(cache_key)
        if hit is None:
            hit = parse_module(reader(key), module, is_package)
            self.entries[cache_key] = hit
        return hit


@dataclass(frozen=True)
class Reach:
    """Result of a closure walk from entry modules."""

    chains: Mapping[str, tuple[str, ...]]  # module -> entry ... module
    edge_kinds: frozenset[str]
    missing_entries: tuple[str, ...]
    parse_errors: Mapping[str, str]  # path -> error, for reached modules only
    dynamic_imports: Mapping[str, tuple[int, ...]]  # path -> lines, for reached modules only

    def reached(self, module: str) -> bool:
        return module in self.chains


class ModuleIndex:
    """Importable modules of one tree, with lazily parsed imports."""

    def __init__(self, paths: Mapping[str, str], reader: Reader, cache: ParseCache | None = None) -> None:
        self._reader = reader
        self._cache = cache if cache is not None else ParseCache()
        self.module_to_path: dict[str, str] = {}
        self.path_to_module: dict[str, str] = {}
        self.shadowed: dict[str, str] = {}
        self._keys = dict(paths)
        has_shim = ROOT_SHIM_PATH in paths
        for path in sorted(paths):
            module = module_name_for_path(path)
            if module is None:
                continue
            if path == SHADOWED_SRC_INIT and has_shim:
                self.shadowed[path] = ROOT_SHIM_PATH
                continue
            self.module_to_path[module] = path
            self.path_to_module[path] = module

    def parsed(self, module: str) -> ParsedModule:
        path = self.module_to_path[module]
        return self._cache.get(self._keys[path], module, path.endswith("__init__.py"), self._reader)

    def _targets(self, ref: ImportRef) -> Iterable[str]:
        parts = ref.target.split(".")
        for index in range(1, len(parts) + 1):
            name = ".".join(parts[:index])
            if name in self.module_to_path:
                yield name
        for imported in ref.from_names:
            sub = f"{ref.target}.{imported}"
            if sub in self.module_to_path:
                yield sub

    def closure(self, entries: Sequence[str], edge_kinds: Iterable[str] = (EDGE_MODULE, EDGE_DEFERRED)) -> Reach:
        kinds = frozenset(edge_kinds)
        chains: dict[str, tuple[str, ...]] = {}
        queue: deque = deque()
        missing: list[str] = []
        for entry in entries:
            if entry not in self.module_to_path:
                missing.append(entry)
                continue
            parts = entry.split(".")
            # Importing a.b.c executes a/__init__ and a.b/__init__ first.
            for index in range(1, len(parts) + 1):
                name = ".".join(parts[:index])
                if name in self.module_to_path and name not in chains:
                    chains[name] = (entry,) if name == entry else (entry, name)
                    queue.append(name)
        parse_errors: dict[str, str] = {}
        dynamic: dict[str, tuple[int, ...]] = {}
        while queue:
            module = queue.popleft()
            parsed = self.parsed(module)
            path = self.module_to_path[module]
            if parsed.parse_error:
                parse_errors[path] = parsed.parse_error
            if parsed.dynamic_import_lines:
                dynamic[path] = parsed.dynamic_import_lines
            for ref in parsed.imports:
                if ref.kind not in kinds:
                    continue
                for target in self._targets(ref):
                    if target not in chains:
                        chains[target] = chains[module] + (target,)
                        queue.append(target)
        return Reach(chains, kinds, tuple(missing), parse_errors, dynamic)


ROLL_FREE = "EXPECTED-ROLL-FREE"
ROLL_SENSITIVE = "EXPECTED-ROLL-SENSITIVE"
UNDECIDABLE = "EXPECTED-UNDECIDABLE"
NOT_IMPORTABLE = "NOT-IMPORTABLE"  # row class for a changed file roll_verdict never considers

LOOP_ENTRY_MODULES: tuple[str, ...] = (
    "weather.collection.snapshot_tracker",
    "weather.market.market_microstructure",
    "weather.operations.observation_trigger",
)
# The execution-tape closure (22 files on the host) is rooted in its supervisor process.
EXECUTION_TAPE_ENTRY_MODULES: tuple[str, ...] = (
    "weather.market.execution_tape_capture",
    "weather.operations.execution_tape_supervisor",
)
SNAPSHOT_MAX_AGE_DAYS = 7
# Module-level imports only.  LOOP_ENTRY_MODULES + EXECUTION_TAPE_ENTRY_MODULES were validated
# against the batch-1 D8 closure union (production 2026-10-05, master 8e179f18, 95 files): the
# module-level walk from the entries reaches 94 of the 95 snapshot files and nothing outside
# it (the 95th, operations/windows_processes.py, is a function-level import of
# market_microstructure that the snapshot carries).  Adding function-level edges reaches 66
# files no loop has loaded, so they are reported per row as INFO (``deferred_chain``) and
# never decide a class.  ``entry_validation`` in every result re-measures this drift.
DEFAULT_EDGE_KINDS: tuple[str, ...] = (EDGE_MODULE,)


def is_importable_candidate(path: str) -> bool:
    """roll_verdict.ps1's filter: ``*.py`` under ``src/`` or ``weather/``, not ``tests/``."""

    return path.endswith(".py") and (path.startswith("src/") or path.startswith("weather/")) and not path.startswith("tests/")


# ---------------------------------------------------------------------------------------
# Closure snapshot
# ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ClosureSnapshot:
    """The production closure union.  ``supplied=False`` means static graph only (labelled)."""

    files: frozenset
    captured: datetime | None
    sha256: str | None
    source: str
    production_master_sha: str | None
    supplied: bool = True
    load_error: str | None = None

    @classmethod
    def static_only(cls) -> "ClosureSnapshot":
        return cls(frozenset(), None, None, "", None, supplied=False)

    @classmethod
    def unreadable(cls, source: str, error: str, sha256: str | None = None) -> "ClosureSnapshot":
        """A supplied snapshot that could not be read: treated as stale (F9), never as absent."""

        return cls(frozenset(), None, sha256, source, None, supplied=True, load_error=error)

    @classmethod
    def from_json_bytes(cls, raw: bytes, source: str = "") -> "ClosureSnapshot":
        data = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(data, dict) or not isinstance(data.get("union_files"), list):
            raise ValueError("closure snapshot has no 'union_files' list")
        captured_text = data.get("captured_local") or data.get("captured_at")
        captured = None
        if captured_text:
            try:
                captured = datetime.fromisoformat(str(captured_text).replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                captured = None
        return cls(
            files=frozenset(str(item).replace("\\", "/") for item in data.get("union_files", [])),
            captured=captured,
            sha256=hashlib.sha256(raw).hexdigest(),
            source=source,
            production_master_sha=data.get("production_master_sha"),
        )

    @classmethod
    def load(cls, path: str) -> "ClosureSnapshot":
        with open(path, "rb") as handle:
            return cls.from_json_bytes(handle.read(), source=path)

    def age_days(self, as_of: datetime) -> float | None:
        if self.captured is None:
            return None
        return (as_of - self.captured) / timedelta(days=1)

    def is_stale(self, as_of: datetime, max_age_days: int = SNAPSHOT_MAX_AGE_DAYS) -> bool:
        if not self.supplied:
            return False  # static graph only: nothing to be stale (labelled and WARNed upstream)
        age = self.age_days(as_of)
        return self.load_error is not None or age is None or age > max_age_days or age < -1

    @property
    def basis(self) -> str:
        if not self.supplied:
            return "static_graph_only"
        return "snapshot+static_graph" if self.load_error is None else "static_graph+unreadable_snapshot"


# ---------------------------------------------------------------------------------------
# Trees
# ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TreeView:
    """A source tree: ``path -> content key`` plus a reader for keys."""

    label: str
    paths: Mapping[str, str]
    reader: Reader


@dataclass(frozen=True)
class GraphOptions:
    loop_entries: tuple[str, ...] = LOOP_ENTRY_MODULES
    include_execution_tape: bool = True
    edge_kinds: tuple[str, ...] = DEFAULT_EDGE_KINDS

    @property
    def entries(self) -> tuple[str, ...]:
        return self.loop_entries + (EXECUTION_TAPE_ENTRY_MODULES if self.include_execution_tape else ())


# ---------------------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class FileRow:
    path: str
    status: str
    importable: bool
    module: str | None
    in_snapshot: bool
    static_chain_base: tuple[str, ...] | None
    static_chain_landing: tuple[str, ...] | None
    schema_family: bool
    known_node: bool
    expected: str
    reasons: tuple[str, ...]
    deferred_chain: tuple[str, ...] | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "path": self.path,
            "status": self.status,
            "importable": self.importable,
            "module": self.module,
            "in_snapshot": self.in_snapshot,
            "static_reached": bool(self.static_chain_base or self.static_chain_landing),
            "static_chain_base": list(self.static_chain_base) if self.static_chain_base else None,
            "static_chain_landing": list(self.static_chain_landing) if self.static_chain_landing else None,
            "deferred_chain_info": list(self.deferred_chain) if self.deferred_chain else None,
            "schema_family": self.schema_family,
            "known_node": self.known_node,
            "expected": self.expected,
            "reasons": list(self.reasons),
            "binding": False,
        }


@dataclass(frozen=True)
class RollClassResult:
    expected: str
    reasons: tuple[str, ...]
    rows: tuple[FileRow, ...]
    changed_count: int
    importable_count: int
    snapshot: ClosureSnapshot
    snapshot_age_days: float | None
    snapshot_stale: bool
    entries: tuple[str, ...]
    edge_kinds: tuple[str, ...]
    missing_entries: Mapping[str, tuple[str, ...]]
    static_closure_size: Mapping[str, int]
    parse_errors: Mapping[str, Mapping[str, str]]
    schema: SchemaAdditiveResult
    graph_complete: bool = True
    extra: dict[str, object] = field(default_factory=dict)

    @property
    def sensitive_files(self) -> tuple[str, ...]:
        return tuple(row.path for row in self.rows if row.expected == ROLL_SENSITIVE)

    def to_json(self) -> dict[str, object]:
        return {
            "expected": self.expected,
            "binding": False,
            "reasons": list(self.reasons),
            "changed_count": self.changed_count,
            "importable_count": self.importable_count,
            "sensitive_files": list(self.sensitive_files),
            "basis": self.snapshot.basis,
            "snapshot": {
                "supplied": self.snapshot.supplied,
                "source": self.snapshot.source or None,
                "sha256": self.snapshot.sha256,
                "captured": self.snapshot.captured.isoformat() if self.snapshot.captured else None,
                "production_master_sha": self.snapshot.production_master_sha,
                "file_count": len(self.snapshot.files),
                "load_error": self.snapshot.load_error,
                "age_days": None if self.snapshot_age_days is None else round(self.snapshot_age_days, 3),
                "stale": self.snapshot_stale,
                "max_age_days": SNAPSHOT_MAX_AGE_DAYS,
            },
            "static_graph": {
                "entries": list(self.entries),
                "edge_kinds": list(self.edge_kinds),
                "missing_entries": {k: list(v) for k, v in self.missing_entries.items()},
                "closure_size": dict(self.static_closure_size),
                "parse_errors": {k: dict(v) for k, v in self.parse_errors.items()},
                "complete": self.graph_complete,
            },
            "schema_additive": self.schema.to_json(),
            "rows": [row.to_json() for row in self.rows],
            **self.extra,
        }


# ---------------------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------------------
def _walk(view: TreeView, options: GraphOptions, cache: ParseCache) -> tuple[ModuleIndex, Reach]:
    index = ModuleIndex(view.paths, view.reader, cache)
    return index, index.closure(options.entries, options.edge_kinds)


def classify(
    changed: Sequence[tuple[str, str]],
    base: TreeView,
    landing: TreeView,
    snapshot: ClosureSnapshot,
    as_of: datetime,
    options: GraphOptions = GraphOptions(),
    cache: ParseCache | None = None,
    schema_reference: TreeView | None = None,
) -> RollClassResult:
    """Classify a landing.

    ``changed`` is ``(status, path)`` for every path the merge writes onto the base;
    ``base`` and ``landing`` are the trees before and after; ``schema_reference``
    overrides the reference tree for the schema-family check (the merge base when the
    merge conflicts and the landing tree is the head tree).
    """

    cache = cache if cache is not None else ParseCache()
    base_index, base_reach = _walk(base, options, cache)
    landing_index, landing_reach = _walk(landing, options, cache)
    parse_errors = {base.label: dict(base_reach.parse_errors), landing.label: dict(landing_reach.parse_errors)}
    graph_complete = not base_reach.parse_errors and not landing_reach.parse_errors \
        and not base_reach.missing_entries and not landing_reach.missing_entries
    stale = snapshot.is_stale(as_of)
    deferred_reach: Reach | None = None
    if EDGE_DEFERRED not in options.edge_kinds:
        deferred_reach = landing_index.closure(options.entries, (EDGE_MODULE, EDGE_DEFERRED))

    rows: list[FileRow] = []
    for status, path in sorted(changed, key=lambda item: item[1]):
        importable = is_importable_candidate(path)
        if not importable:
            rows.append(FileRow(path, status, False, None, False, None, None, False, False, NOT_IMPORTABLE,
                                ("not *.py under src/ or weather/: roll-free by contract",)))
            continue
        module = landing_index.path_to_module.get(path) or base_index.path_to_module.get(path)
        shadowed = path in landing_index.shadowed or path in base_index.shadowed
        in_snapshot = path in snapshot.files
        chain_base = base_reach.chains.get(module) if module and path in base_index.path_to_module else None
        chain_landing = landing_reach.chains.get(module) if module and path in landing_index.path_to_module else None
        family = is_schema_family(path)
        known = module is not None or shadowed
        reasons: list[str] = []
        if in_snapshot:
            reasons.append("in closure snapshot")
        if chain_base:
            reasons.append("static graph (base): " + " -> ".join(chain_base))
        if chain_landing:
            reasons.append("static graph (landing): " + " -> ".join(chain_landing))
        if family:
            reasons.append("schema_registry* family: always roll-sensitive")
        if in_snapshot or chain_base or chain_landing or family:
            expected = ROLL_SENSITIVE
        elif not known:
            expected = UNDECIDABLE
            reasons.append("in neither the snapshot nor the static graph's module index")
        elif not graph_complete:
            expected = UNDECIDABLE
            reasons.append("static graph incomplete (a reached module failed to parse or an entry is missing)")
        else:
            expected = ROLL_FREE
            if shadowed:
                reasons.append("shadowed by the weather/__init__.py root shim; never executed by a loop")
            elif snapshot.supplied:
                reasons.append("not in the snapshot and not reached from the loop entries")
            else:
                reasons.append("not reached from the loop entries (static graph only: no closure snapshot)")
        deferred = None
        if deferred_reach is not None and module and expected != ROLL_SENSITIVE:
            deferred = deferred_reach.chains.get(module)
            if deferred:
                reasons.append("INFO: reachable only through a function-level import: " + " -> ".join(deferred))
        rows.append(FileRow(path, status, True, module, in_snapshot, chain_base, chain_landing, family, known,
                            expected, tuple(reasons), deferred))

    importable_rows = [row for row in rows if row.importable]
    if any(row.expected == ROLL_SENSITIVE for row in importable_rows):
        expected = ROLL_SENSITIVE
        reasons = (f"{sum(r.expected == ROLL_SENSITIVE for r in importable_rows)} importable file(s) expected to roll",)
    elif any(row.expected == UNDECIDABLE for row in importable_rows):
        expected = UNDECIDABLE
        reasons = ("a changed importable file could not be placed; schedule as roll-sensitive",)
    elif importable_rows and stale:
        expected = UNDECIDABLE
        reasons = (f"closure snapshot older than {SNAPSHOT_MAX_AGE_DAYS} days or unreadable; schedule as roll-sensitive",)
    elif importable_rows:
        expected = ROLL_FREE
        reasons = ("no importable file in the snapshot, the static graph or the schema family",)
    else:
        expected = ROLL_FREE
        reasons = ("no importable files (docs/config/tests/ps1 only)",)

    reference = schema_reference or base
    schema = classify_schema_change(
        reference.paths,
        landing.paths,
        reference.reader,
        landing.reader,
        changed_paths=[path for _, path in changed],
        reference_label=reference.label,
        candidate_label=landing.label,
    )
    age = snapshot.age_days(as_of)
    return RollClassResult(
        expected=expected,
        reasons=reasons,
        rows=tuple(rows),
        changed_count=len(rows),
        importable_count=len(importable_rows),
        snapshot=snapshot,
        snapshot_age_days=age,
        snapshot_stale=stale,
        entries=options.entries,
        edge_kinds=options.edge_kinds,
        missing_entries={base.label: base_reach.missing_entries, landing.label: landing_reach.missing_entries},
        static_closure_size={base.label: len(base_reach.chains), landing.label: len(landing_reach.chains)},
        parse_errors=parse_errors,
        schema=schema,
        graph_complete=graph_complete,
        extra={"entry_validation": entry_validation(base_index, base_reach, snapshot, base.label)},
    )


def entry_validation(index: ModuleIndex, reach: Reach, snapshot: ClosureSnapshot, label: str) -> dict[str, object]:
    """Drift between the static walk and the snapshot (the LOOP_ENTRY_MODULES validation)."""

    reached = {index.module_to_path[module] for module in reach.chains}
    out: dict[str, object] = {"tree": label, "static_reached": len(reached)}
    if not snapshot.supplied or snapshot.load_error is not None:
        out["snapshot_compared"] = False
        return out
    in_tree = {path for path in snapshot.files if path in index.path_to_module or path in index.shadowed}
    out.update({
        "snapshot_compared": True,
        "snapshot_files": len(snapshot.files),
        "snapshot_files_in_tree": len(in_tree),
        "snapshot_reached": len(in_tree & reached),
        "snapshot_not_reached": sorted(in_tree - reached),
        "reached_not_in_snapshot": sorted(reached - snapshot.files),
    })
    return out


def static_closure_files(view: TreeView, options: GraphOptions = GraphOptions(), cache: ParseCache | None = None) -> dict[str, tuple[str, ...]]:
    """``path -> chain`` for every module reached from the entries; for validating entries."""

    index, reach = _walk(view, options, cache if cache is not None else ParseCache())
    return {index.module_to_path[module]: chain for module, chain in reach.chains.items()}
