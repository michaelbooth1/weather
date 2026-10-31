"""Family schema loader for the split schema registry (Data Layer v2 PL-2).

The registry has two halves:

* **core** -- ``schema_registry.py``, ``schema_registry_data.py``,
  ``schema_registry_recent_data.py``, ``schema_registry_types.py`` and this
  module (the whole ``src/weather/schema_registry*.py`` family). The capture
  loops import the core, so any edit to it rolls every loop. It is frozen: the
  specs the loops need stay here unchanged, pinned by a parity digest in
  ``tests/operations/test_schema_families_registry.py``.
* **families** -- one module per capture family under
  ``src/weather/schema_families/<family>.py``. No loop imports them, so adding
  or changing one is roll-free under ``scripts/ops/roll_verdict.ps1``.

This module only *finds* family modules; it never imports one at import time.
Discovery lists ``*.py`` files in the package directory and imports each one
by a computed name only when ``load_families()`` is called (the strict audit,
the family lookup and tests). The loops never call it, so family modules never
enter a loop closure; ``weather.schema_registry`` imports this module only inside
``audit_payload``. ``weather.schema_registry.schema_version`` and the core lookup
maps are unchanged and do not see family schemas.

A family module defines ``SCHEMAS`` (a tuple of ``SchemaSpec``) and may define
``EXCLUDED_SCHEMA_LITERALS`` (a tuple of ``SchemaLiteralExclusion``). It may
import only ``weather.schema_registry_types``; a family producer resolves its
versions through ``weather.schema_families.schema_version``.
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from weather.schema_registry_data import (
    EXCLUDED_SCHEMA_LITERALS,
    REGISTERED_SCHEMAS,
    SchemaLiteralExclusion,
    SchemaSpec,
)

FAMILY_PACKAGE = "weather.schema_families"
FAMILY_PACKAGE_DIR = Path(__file__).resolve().parent / "schema_families"
FAMILY_MODULE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class SchemaFamilyError(ValueError):
    """A family module is malformed or collides with the core or another family."""


@dataclass(frozen=True)
class SchemaFamily:
    family: str
    module: str
    schemas: tuple[SchemaSpec, ...]
    exclusions: tuple[SchemaLiteralExclusion, ...] = ()


@dataclass(frozen=True)
class FamilyRegistry:
    """Core plus every family; ``errors`` lists every family that was refused."""

    families: tuple[SchemaFamily, ...]
    errors: tuple[str, ...]

    @property
    def family_schemas(self) -> tuple[SchemaSpec, ...]:
        return tuple(spec for family in self.families for spec in family.schemas)

    @property
    def family_exclusions(self) -> tuple[SchemaLiteralExclusion, ...]:
        return tuple(item for family in self.families for item in family.exclusions)

    @property
    def schemas(self) -> tuple[SchemaSpec, ...]:
        return REGISTERED_SCHEMAS + self.family_schemas

    @property
    def exclusions(self) -> tuple[SchemaLiteralExclusion, ...]:
        return EXCLUDED_SCHEMA_LITERALS + self.family_exclusions

    def family_of(self, name: str) -> str | None:
        for family in self.families:
            if any(spec.name == name for spec in family.schemas):
                return family.family
        return None


def family_module_names(package_dir: Path = FAMILY_PACKAGE_DIR) -> tuple[str, ...]:
    """Family module names: ``*.py`` in the package directory, ``_``-prefixed files skipped."""

    directory = Path(package_dir)
    if not directory.is_dir():
        return ()
    return tuple(sorted(path.stem for path in directory.glob("*.py") if not path.stem.startswith("_")))


def _load_one(package: str, name: str) -> SchemaFamily:
    if not FAMILY_MODULE_RE.match(name):
        raise SchemaFamilyError(f"{name}: family module names must match {FAMILY_MODULE_RE.pattern}")
    module_name = f"{package}.{name}"
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # a broken family must fail the audit, never the caller's process
        raise SchemaFamilyError(f"{name}: import failed: {type(exc).__name__}: {exc}") from exc
    schemas = getattr(module, "SCHEMAS", None)
    exclusions = getattr(module, "EXCLUDED_SCHEMA_LITERALS", ())
    if not isinstance(schemas, tuple) or not schemas or not all(isinstance(s, SchemaSpec) for s in schemas):
        raise SchemaFamilyError(f"{name}: SCHEMAS must be a non-empty tuple of SchemaSpec")
    if not isinstance(exclusions, tuple) or not all(isinstance(e, SchemaLiteralExclusion) for e in exclusions):
        raise SchemaFamilyError(f"{name}: EXCLUDED_SCHEMA_LITERALS must be a tuple of SchemaLiteralExclusion")
    for spec in schemas:
        if not spec.owner:
            raise SchemaFamilyError(f"{name}: {spec.name} has no owner")
    return SchemaFamily(name, module_name, schemas, exclusions)


def load_families(package_dir: Path = FAMILY_PACKAGE_DIR, package: str = FAMILY_PACKAGE) -> FamilyRegistry:
    """Import every family module and check it against the core and the other families.

    A family whose names or versions collide with the core, an earlier family or
    an exclusion is refused whole and reported in ``errors``; the core is never
    shadowed.
    """

    names = {spec.name: "core" for spec in REGISTERED_SCHEMAS}
    versions = {spec.version: "core" for spec in REGISTERED_SCHEMAS}
    excluded = {item.version: "core" for item in EXCLUDED_SCHEMA_LITERALS}
    accepted: list[SchemaFamily] = []
    errors: list[str] = []
    for name in family_module_names(package_dir):
        try:
            family = _load_one(package, name)
        except SchemaFamilyError as exc:
            errors.append(str(exc))
            continue
        clashes: list[str] = []
        local_names: set[str] = set()
        local_versions: set[str] = set()
        for spec in family.schemas:
            if spec.name in names or spec.name in local_names:
                clashes.append(f"name {spec.name} already registered by {names.get(spec.name, name)}")
            if spec.version in versions or spec.version in local_versions or spec.version in excluded:
                owner = versions.get(spec.version) or excluded.get(spec.version) or name
                clashes.append(f"version {spec.version} already registered or excluded by {owner}")
            local_names.add(spec.name)
            local_versions.add(spec.version)
        for item in family.exclusions:
            if item.version in versions or item.version in excluded or item.version in local_versions:
                clashes.append(f"exclusion {item.version} collides with a registered or excluded version")
        if clashes:
            errors.append(f"{name}: refused: " + "; ".join(clashes))
            continue
        accepted.append(family)
        names.update({spec.name: name for spec in family.schemas})
        versions.update({spec.version: name for spec in family.schemas})
        excluded.update({item.version: name for item in family.exclusions})
    return FamilyRegistry(tuple(accepted), tuple(errors))


@lru_cache(maxsize=1)
def installed_families() -> FamilyRegistry:
    """The installed families, loaded once per process."""

    return load_families()


def family_schema_version(name: str) -> str:
    """Active version for a core or family schema name (the lookup family producers use)."""

    for spec in REGISTERED_SCHEMAS:
        if spec.name == name:
            return spec.version
    for spec in installed_families().family_schemas:
        if spec.name == name:
            return spec.version
    raise KeyError(f"unknown schema registry name: {name}")


__all__ = [
    "FAMILY_PACKAGE",
    "FAMILY_PACKAGE_DIR",
    "FamilyRegistry",
    "SchemaFamily",
    "SchemaFamilyError",
    "family_module_names",
    "family_schema_version",
    "installed_families",
    "load_families",
]
