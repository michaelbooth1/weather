"""Split schema registry (Data Layer v2 PL-2): frozen core, roll-free family modules.

Guards: docs/operations/DATA_LAYER_V2_PLAN.md S3 / PL-2 (strict schema audit passes; a dummy
family schema diff is roll-free) and DELEGATION_CONTRACT.md §3 (the schema_registry* core sits in
every capture closure).

* the core registry content is byte-for-byte the pre-split registry (parity digest);
* a family module registers through the strict audit without touching the core, and every
  collision with the core, another family or an exclusion is refused;
* no capture loop entry reaches ``weather/schema_families`` by any import edge;
* the roll-class engine predicts a dummy family addition ROLL-FREE and a core addition
  ROLL-SENSITIVE (``test_schema_families_roll_verdict.py`` runs the binding script).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pytest

import weather.schema_families as schema_families
import weather.schema_registry_families as loader
from weather import schema_registry, schema_registry_data
from weather.operations.landing_preflight_rollclass_graph import (
    EDGE_DEFERRED,
    EDGE_MODULE,
    ROLL_FREE,
    ROLL_SENSITIVE,
    ClosureSnapshot,
    GraphOptions,
    TreeView,
    classify,
    static_closure_files,
)
from weather.operations.landing_preflight_rollclass_schema import (
    ADDITIVE,
    NOT_APPLICABLE,
    PATH_ROLL_FREE_UNLESS_IMPORTED,
    PATH_ROLL_SENSITIVE,
    SCHEMA_PART_CORE,
    SCHEMA_PART_FAMILY,
    SCHEMA_PART_FAMILY_PACKAGE,
    classify_schema_path,
)

pytestmark = pytest.mark.ratchet

REPO_ROOT = Path(__file__).resolve().parents[2]

# sha256 of the canonical core registry content on the S3 base d69842131 (stack6 + S1, before the PL-2 split;
# re-pinned from 01cad4b91 for the stack6 feature_store v1.17 core change):
# registry_payload(), every exclusion, the alias table and both lookup maps. The core is frozen;
# a change here is a roll-sensitive landing that re-pins this digest on purpose, never in passing.
CORE_REGISTRY_SHA256 = "a384a71a34fe96e3d136dd0345a053e7ed571f63302b0c087814a0d2893d6e4a"
CORE_SCHEMA_COUNT = 645
CORE_EXCLUSION_COUNT = 14

FAMILY_MODULE = '''from weather.schema_registry_types import SchemaLiteralExclusion, SchemaSpec

SCHEMAS = (
    SchemaSpec("{name}", "{version}", "weather.dummy_capture", "active", "Dummy capture family rows."),
)
EXCLUDED_SCHEMA_LITERALS = {exclusions}
'''


def _core_digest() -> str:
    payload = {
        "registry": schema_registry.registry_payload(),
        "exclusions": [asdict(item) for item in schema_registry_data.EXCLUDED_SCHEMA_LITERALS],
        "aliases": schema_registry_data.INTENTIONAL_SCHEMA_VERSION_ALIASES,
        "by_name": {k: v.version for k, v in sorted(schema_registry_data.SCHEMAS_BY_NAME.items())},
        "by_version": {k: v.name for k, v in sorted(schema_registry_data.SCHEMAS_BY_VERSION.items())},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _family_package(tmp_path: Path, monkeypatch, modules: dict[str, str]) -> tuple[Path, str]:
    package = f"s3_dummy_families_{uuid.uuid4().hex[:8]}"
    directory = tmp_path / package
    directory.mkdir()
    (directory / "__init__.py").write_text("", encoding="utf-8")
    for name, text in modules.items():
        (directory / f"{name}.py").write_text(text, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    return directory, package


def _family(name: str = "dummy_capture_rows", version: str = "dummy_capture_rows_v0.1", exclusions: str = "()") -> str:
    return FAMILY_MODULE.format(name=name, version=version, exclusions=exclusions)


def test_core_registry_content_is_the_pre_split_registry_byte_for_byte():
    assert len(schema_registry_data.REGISTERED_SCHEMAS) == CORE_SCHEMA_COUNT
    assert len(schema_registry_data.EXCLUDED_SCHEMA_LITERALS) == CORE_EXCLUSION_COUNT
    assert _core_digest() == CORE_REGISTRY_SHA256, (
        "the frozen schema_registry* core changed: that rolls every capture loop. Register a new "
        "capture family's schema in src/weather/schema_families/<family>.py instead; re-pin this "
        "digest only inside a planned roll-sensitive landing"
    )


def test_installed_families_are_clean_and_the_strict_source_audit_passes():
    registry = loader.load_families()
    assert registry.errors == ()
    payload = schema_registry.audit_payload(["src"])
    assert payload["unregistered_versions"] == []
    assert payload["family_error_count"] == 0
    assert payload["core_registered_count"] == CORE_SCHEMA_COUNT
    assert payload["registered_count"] == CORE_SCHEMA_COUNT + payload["family_registered_count"]


def test_dummy_family_registers_through_the_audit_without_touching_the_core(tmp_path, monkeypatch):
    directory, package = _family_package(tmp_path, monkeypatch, {"dummy_capture": _family()})
    scanned = tmp_path / "producer"
    scanned.mkdir()
    (scanned / "producer.py").write_text('SCHEMA = "dummy_capture_rows_v0.1"\n', encoding="utf-8")

    registry = loader.load_families(directory, package)

    assert registry.errors == ()
    assert [family.family for family in registry.families] == ["dummy_capture"]
    assert registry.family_of("dummy_capture_rows") == "dummy_capture"
    with_family = schema_registry.audit_payload([str(scanned)], registry=registry)
    assert with_family["unregistered_versions"] == []
    assert with_family["family_registered_count"] == 1
    assert with_family["schema_families"][0]["schemas"] == ["dummy_capture_rows"]
    core_only = schema_registry.audit_payload([str(scanned)], registry=loader.FamilyRegistry((), ()))
    assert core_only["unregistered_versions"] == ["dummy_capture_rows_v0.1"]
    # The core lookup the loops use never sees a family schema.
    with pytest.raises(KeyError):
        schema_registry.schema_version("dummy_capture_rows")
    assert "dummy_capture_rows" not in schema_registry_data.SCHEMAS_BY_NAME
    assert _core_digest() == CORE_REGISTRY_SHA256


def test_family_lookup_answers_core_and_family_names(tmp_path, monkeypatch):
    directory, package = _family_package(tmp_path, monkeypatch, {"dummy_capture": _family()})
    registry = loader.load_families(directory, package)
    monkeypatch.setattr(loader, "installed_families", lambda: registry)

    assert schema_families.schema_version("dummy_capture_rows") == "dummy_capture_rows_v0.1"
    assert schema_families.schema_version("feature_store") == schema_registry.schema_version("feature_store")
    with pytest.raises(KeyError):
        schema_families.schema_version("no_such_family_rows")


@pytest.mark.parametrize(
    ("modules", "fragment"),
    [
        ({"clash": _family(name="feature_store", version="dummy_capture_rows_v0.1")}, "name feature_store"),
        ({"clash": _family(version="toronto_feature_store_v1.16")}, "version toronto_feature_store_v1.16"),
        ({"clash": _family(version="maker_default_v0")}, "version maker_default_v0"),
        ({"a_first": _family(), "b_second": _family(version="dummy_capture_rows_v0.2")}, "name dummy_capture_rows"),
        ({"a_first": _family(), "b_second": _family(name="other_rows")}, "version dummy_capture_rows_v0.1"),
        ({"clash": _family(exclusions='(SchemaLiteralExclusion("historical_coverage_v1", "o", "c", "not a schema"),)')},
         "exclusion historical_coverage_v1"),
        ({"empty": "SCHEMAS = ()\n"}, "non-empty tuple of SchemaSpec"),
        ({"broken": "raise RuntimeError('boom')\n"}, "import failed"),
        ({"BadName": _family()}, "must match"),
    ],
)
def test_family_collisions_and_malformed_modules_are_refused(tmp_path, monkeypatch, modules, fragment):
    directory, package = _family_package(tmp_path, monkeypatch, modules)

    registry = loader.load_families(directory, package)

    assert len(registry.errors) == 1 and fragment in registry.errors[0], registry.errors
    # A refused family registers nothing; the first of two clashing families stays.
    assert all(family.family == "a_first" for family in registry.families)
    assert registry.schemas[:CORE_SCHEMA_COUNT] == schema_registry_data.REGISTERED_SCHEMAS


def test_strict_audit_cli_fails_on_a_refused_family(tmp_path, monkeypatch, capsys):
    directory, package = _family_package(tmp_path, monkeypatch, {"clash": _family(name="feature_store")})
    registry = loader.load_families(directory, package)
    monkeypatch.setattr(loader, "installed_families", lambda: registry)
    scanned = tmp_path / "empty_scan"
    scanned.mkdir()
    out = tmp_path / "audit.json"

    with pytest.raises(SystemExit) as raised:
        schema_registry.main(["audit", "--strict", "--paths", str(scanned), "--out", str(out)])

    assert raised.value.code == 1
    assert json.loads(out.read_text(encoding="utf-8"))["family_error_count"] == 1
    assert "family error: clash: refused" in capsys.readouterr().out
    # Without --strict the audit reports and exits normally.
    schema_registry.main(["audit", "--paths", str(scanned), "--out", str(out)])


def test_schema_path_classifier_maps_each_half_of_the_split():
    for path in ("src/weather/schema_registry.py", "src/weather/schema_registry_data.py",
                 "src/weather/schema_registry_recent_data.py", "src/weather/schema_registry_types.py",
                 "src/weather/schema_registry_families.py"):
        cls = classify_schema_path(path)
        assert (cls.part, cls.family, cls.roll_class) == (SCHEMA_PART_CORE, None, PATH_ROLL_SENSITIVE), path
    family = classify_schema_path("src/weather/schema_families/dummy_capture.py")
    assert (family.part, family.family, family.roll_class) == (
        SCHEMA_PART_FAMILY, "dummy_capture", PATH_ROLL_FREE_UNLESS_IMPORTED)
    package = classify_schema_path("src/weather/schema_families/__init__.py")
    assert (package.part, package.family) == (SCHEMA_PART_FAMILY_PACKAGE, None)
    assert classify_schema_path("src\\weather\\schema_families\\dummy_capture.py").family == "dummy_capture"
    for outside in ("src/weather/schema_families/sub/x.py", "src/weather/schema_families/notes.md",
                    "src/weather/sources/historical_schema.py", "tests/operations/test_schema_registry.py",
                    "src/weather/market/schema_registry.py"):
        assert classify_schema_path(outside) is None, outside


def _worktree_view() -> TreeView:
    paths = {}
    for base in ("src", "weather"):
        for file in (REPO_ROOT / base).rglob("*.py"):
            rel = file.relative_to(REPO_ROOT).as_posix()
            if "__pycache__" not in rel:
                paths[rel] = rel
    return TreeView("worktree", paths, lambda key: (REPO_ROOT / key).read_bytes())


def test_no_capture_loop_reaches_a_schema_families_module():
    view = _worktree_view()
    module_level = static_closure_files(view, GraphOptions(edge_kinds=(EDGE_MODULE,)))
    every_edge = static_closure_files(view, GraphOptions(edge_kinds=(EDGE_MODULE, EDGE_DEFERRED)))

    assert "src/weather/schema_registry.py" in module_level  # the entries still reach the core
    assert not [path for path in every_edge if path.startswith("src/weather/schema_families/")]
    # The loader is reached only through the audit's function-level import, never at import time.
    assert "src/weather/schema_registry_families.py" not in module_level


def _overlay(view: TreeView, label: str, added: dict[str, bytes]) -> TreeView:
    paths = dict(view.paths)
    paths.update({path: f"overlay:{path}" for path in added})

    def reader(key: str) -> bytes:
        if key.startswith("overlay:"):
            return added[key[len("overlay:"):]]
        return view.reader(key)

    return TreeView(label, paths, reader)


def test_roll_class_engine_predicts_a_dummy_family_roll_free_and_a_core_addition_roll_sensitive():
    base = _worktree_view()
    closure = sorted(static_closure_files(base, GraphOptions()))
    now = datetime.now()
    snapshot = ClosureSnapshot.from_json_bytes(
        json.dumps({"union_files": closure, "captured_local": now.isoformat()}).encode("utf-8"), source="fixture")

    family_path = "src/weather/schema_families/dummy_capture.py"
    landing = _overlay(base, "landing", {family_path: _family().encode("utf-8")})
    result = classify([("A", family_path)], base, landing, snapshot, now)

    assert result.expected == ROLL_FREE, result.to_json()
    assert result.schema.status == NOT_APPLICABLE
    (row,) = result.rows
    assert any("PL-2 family schema" in reason for reason in row.reasons)

    core_path = "src/weather/schema_registry_recent_data.py"
    core_text = (REPO_ROOT / core_path).read_text(encoding="utf-8")
    added = core_text.replace(
        "RECENT_REGISTERED_SCHEMAS = (\n",
        'RECENT_REGISTERED_SCHEMAS = (\n    SchemaSpec("dummy_capture_rows", "dummy_capture_rows_v0.1", "o", "active"),\n', 1)
    assert added != core_text
    core_landing = _overlay(base, "landing", {core_path: added.encode("utf-8")})
    core_result = classify([("M", core_path)], base, core_landing, snapshot, now)

    assert core_result.expected == ROLL_SENSITIVE
    assert core_result.schema.status == ADDITIVE
