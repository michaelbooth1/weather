"""Landing preflight: mechanical additive-only check for the schema-registry family (L-P4).

Ported from the Swarm L L-R3 classifier (stdlib only); shared by ``roll_class``
and L-P2's ``schema_registry`` check.

Rule (AGREED §1 step 8): a change to the ``schema_registry*`` family is ADDITIVE iff every
``SchemaSpec(...)`` entry of the reference tree is still present, literal-identical
(same AST, keywords order-insensitive), and the only difference is new entries.
Anything else is NOT_ADDITIVE. The family is always roll-sensitive whatever this says;
additivity only decides whether the change may share a batch (M2 caps).

``SchemaLiteralExclusion(...)`` entries and the rest of the family's code are compared
too and reported, but only ``SchemaSpec`` entries decide the class. Code outside the
entries that changed is reported as ``non_entry_code_changed`` (INFO).
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass, field
from collections.abc import Callable, Mapping

SCHEMA_FAMILY_PREFIX = "src/weather/schema_registry"
ENTRY_CALLS = ("SchemaSpec",)
INFO_CALLS = ("SchemaLiteralExclusion",)

ADDITIVE = "ADDITIVE"
NOT_ADDITIVE = "NOT_ADDITIVE"
NO_ENTRY_CHANGE = "NO_ENTRY_CHANGE"
NOT_APPLICABLE = "NOT_APPLICABLE"
UNPARSEABLE = "UNPARSEABLE"

Reader = Callable[[str], bytes]


def is_schema_family(path: str) -> bool:
    return path.startswith(SCHEMA_FAMILY_PREFIX) and path.endswith(".py") and "/" not in path[len("src/weather/") :]


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _canonical(node: ast.Call) -> str:
    keywords = sorted(node.keywords, key=lambda kw: kw.arg or "")
    clone = ast.Call(func=node.func, args=node.args, keywords=keywords)
    return ast.dump(clone, annotate_fields=True, include_attributes=False)


def _entry_label(node: ast.Call) -> str:
    values: list[str] = []
    for arg in node.args[:2]:
        if isinstance(arg, ast.Constant):
            values.append(repr(arg.value))
        elif isinstance(arg, ast.Name):
            values.append(arg.id)
        else:
            values.append("<expr>")
    return f"{_call_name(node)}({', '.join(values)})"


def _entry_identity(node: ast.Call) -> str | None:
    """``name`` (first positional) for pairing a removed entry with its replacement."""

    if node.args and isinstance(node.args[0], ast.Constant):
        return str(node.args[0].value)
    for keyword in node.keywords:
        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
            return str(keyword.value.value)
    return None


def _is_entry(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _call_name(node) in ENTRY_CALLS + INFO_CALLS


class _Strip(ast.NodeTransformer):
    """Remove entries from tuples/lists so adding an entry leaves the skeleton unchanged."""

    def _sequence(self, node: ast.AST) -> ast.AST:
        node.elts = [elt for elt in node.elts if not _is_entry(elt)]  # type: ignore[attr-defined]
        return self.generic_visit(node)

    visit_Tuple = _sequence
    visit_List = _sequence

    def visit_Call(self, node: ast.Call) -> ast.AST:
        if _is_entry(node):
            return ast.Constant(value="<entry>")
        return self.generic_visit(node)


@dataclass
class FamilyEntries:
    entries: Counter = field(default_factory=Counter)  # canonical -> count
    labels: dict[str, str] = field(default_factory=dict)
    identities: dict[str, str | None] = field(default_factory=dict)
    info_entries: Counter = field(default_factory=Counter)
    skeleton: dict[str, str] = field(default_factory=dict)  # path -> AST dump without entries
    parse_errors: dict[str, str] = field(default_factory=dict)


def collect(paths: Mapping[str, str], reader: Reader) -> FamilyEntries:
    result = FamilyEntries()
    for path in sorted(paths):
        if not is_schema_family(path):
            continue
        try:
            tree = ast.parse(reader(paths[path]))
        except (SyntaxError, ValueError) as exc:
            result.parse_errors[path] = f"{type(exc).__name__}: {exc}"
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _call_name(node)
                if name in ENTRY_CALLS:
                    key = _canonical(node)
                    result.entries[key] += 1
                    result.labels.setdefault(key, _entry_label(node))
                    result.identities.setdefault(key, _entry_identity(node))
                elif name in INFO_CALLS:
                    result.info_entries[_canonical(node)] += 1
        result.skeleton[path] = ast.dump(_Strip().visit(tree), include_attributes=False)
    return result


@dataclass(frozen=True)
class SchemaAdditiveResult:
    status: str
    family_paths_changed: tuple[str, ...]
    added: tuple[str, ...]
    removed_or_changed: tuple[str, ...]
    changed_identities: tuple[str, ...]
    exclusions_added: int
    exclusions_removed: int
    non_entry_code_changed: tuple[str, ...]
    parse_errors: Mapping[str, str]
    reference: str
    candidate: str

    def to_json(self) -> dict[str, object]:
        return {
            "status": self.status,
            "family_paths_changed": list(self.family_paths_changed),
            "entries_added": list(self.added),
            "entries_removed_or_changed": list(self.removed_or_changed),
            "changed_identities": list(self.changed_identities),
            "exclusions_added": self.exclusions_added,
            "exclusions_removed": self.exclusions_removed,
            "non_entry_code_changed": list(self.non_entry_code_changed),
            "parse_errors": dict(self.parse_errors),
            "reference": self.reference,
            "candidate": self.candidate,
            "rule": "ADDITIVE iff every reference SchemaSpec entry is literal-identical in the candidate and only new entries appear",
        }


def classify_schema_change(
    reference_paths: Mapping[str, str],
    candidate_paths: Mapping[str, str],
    reference_reader: Reader,
    candidate_reader: Reader,
    changed_paths: list[str] | None = None,
    reference_label: str = "base",
    candidate_label: str = "landing",
) -> SchemaAdditiveResult:
    family_changed = tuple(
        sorted(
            path
            for path in (changed_paths if changed_paths is not None else set(reference_paths) | set(candidate_paths))
            if is_schema_family(path) and reference_paths.get(path) != candidate_paths.get(path)
        )
    )
    if not family_changed:
        return SchemaAdditiveResult(NOT_APPLICABLE, (), (), (), (), 0, 0, (), {}, reference_label, candidate_label)
    ref = collect(reference_paths, reference_reader)
    cand = collect(candidate_paths, candidate_reader)
    errors = {**{f"{reference_label}:{p}": e for p, e in ref.parse_errors.items()},
              **{f"{candidate_label}:{p}": e for p, e in cand.parse_errors.items()}}
    missing = ref.entries - cand.entries
    added = cand.entries - ref.entries
    removed_labels = tuple(sorted(ref.labels[key] for key in missing.elements()))
    added_labels = tuple(sorted(cand.labels[key] for key in added.elements()))
    removed_ids = {ref.identities.get(key) for key in missing}
    added_ids = {cand.identities.get(key) for key in added}
    changed_ids = tuple(sorted(i for i in removed_ids & added_ids if i))
    skeleton_changed = tuple(
        sorted(
            path
            for path in set(ref.skeleton) | set(cand.skeleton)
            if ref.skeleton.get(path) != cand.skeleton.get(path)
        )
    )
    if errors:
        status = UNPARSEABLE
    elif missing:
        status = NOT_ADDITIVE
    elif added:
        status = ADDITIVE
    else:
        status = NO_ENTRY_CHANGE
    return SchemaAdditiveResult(
        status,
        family_changed,
        added_labels,
        removed_labels,
        changed_ids,
        sum((cand.info_entries - ref.info_entries).values()),
        sum((ref.info_entries - cand.info_entries).values()),
        skeleton_changed,
        errors,
        reference_label,
        candidate_label,
    )
