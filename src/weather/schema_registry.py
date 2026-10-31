"""Central schema-version registry and migration audit tooling.

The registry is intentionally dependency-free: producer modules import schema
constants from here, while this module never imports producers.

Split (Data Layer v2 PL-2): this module and its ``schema_registry_*`` data shards
are the frozen *core* that the capture loops import. New capture families
register their schemas in ``weather/schema_families/<family>.py`` instead, which
no loop imports, so adding one is roll-free. ``schema_version`` and the lookup
maps answer for the core only; ``audit_payload`` (the strict audit) loads the
families through ``weather.schema_registry_families`` and checks both halves.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict
from pathlib import Path

from weather.schema_registry_data import (
    EXCLUDED_SCHEMA_LITERAL_BY_VERSION,
    EXCLUDED_SCHEMA_LITERALS,
    REGISTERED_SCHEMAS,
    SCHEMA_REGISTRY_SCHEMA_VERSION,
    SCHEMAS_BY_NAME,
    SCHEMAS_BY_VERSION,
    SchemaLiteralExclusion,
    SchemaSpec,
)

SCHEMA_LITERAL_RE = re.compile(
    r"""['"]([a-z][a-z0-9]*(?:_[a-z0-9]+)*_v\d+(?:\.\d+)?|toronto_feature_store_v\d+(?:\.\d+)?)['"]"""
)
DEFAULT_SCAN_SUFFIXES = {".py"}
DEFAULT_IGNORE_DIRS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "artifacts",
    "data",
    "node_modules",
    "venv",
}


def schema_version(name: str) -> str:
    """Return the active schema version for a registered schema name."""
    try:
        return SCHEMAS_BY_NAME[name].version
    except KeyError as exc:
        raise KeyError(f"unknown schema registry name: {name}") from exc


def registered_schema(name: str) -> dict:
    return asdict(SCHEMAS_BY_NAME[name])


def registry_payload() -> dict:
    return {
        "schema_version": SCHEMA_REGISTRY_SCHEMA_VERSION,
        "schemas": [asdict(spec) for spec in REGISTERED_SCHEMAS],
    }


def validate_schema_version(name: str, version: str) -> bool:
    return schema_version(name) == version


def _iter_scan_files(paths, suffixes=DEFAULT_SCAN_SUFFIXES):
    for item in paths:
        path = Path(item)
        if not path.exists():
            continue
        if path.is_file():
            if path.suffix in suffixes:
                yield path
            continue
        for child in path.rglob("*"):
            if any(part in DEFAULT_IGNORE_DIRS for part in child.parts):
                continue
            if child.is_file() and child.suffix in suffixes:
                yield child


def scan_schema_literals(paths=("src",), suffixes=DEFAULT_SCAN_SUFFIXES, registry=None):
    """Find schema-looking string literals in source files.

    ``registry`` (a ``FamilyRegistry``) adds the family schemas and exclusions to
    the core lookup; without it only the core is consulted.
    """
    by_version = SCHEMAS_BY_VERSION
    exclusion_by_version = EXCLUDED_SCHEMA_LITERAL_BY_VERSION
    if registry is not None:
        by_version = {**SCHEMAS_BY_VERSION, **{spec.version: spec for spec in registry.family_schemas}}
        exclusion_by_version = {
            **EXCLUDED_SCHEMA_LITERAL_BY_VERSION,
            **{item.version: item for item in registry.family_exclusions},
        }
    rows = []
    for path in sorted(set(_iter_scan_files(paths, suffixes=suffixes))):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(lines, start=1):
            for match in SCHEMA_LITERAL_RE.finditer(line):
                version = match.group(1)
                spec = by_version.get(version)
                exclusion = exclusion_by_version.get(version)
                rows.append({
                    "path": str(path),
                    "line": line_no,
                    "version": version,
                    "registered": spec is not None,
                    "schema_name": spec.name if spec else None,
                    "excluded": exclusion is not None,
                    "exclusion_classification": exclusion.classification if exclusion else None,
                    "exclusion_reason": exclusion.reason if exclusion else None,
                })
    return rows


def audit_payload(paths=("src",), registry=None) -> dict:
    """The literal audit over core plus families (``registry`` defaults to the installed families)."""
    if registry is None:
        # Deferred so the capture loops, which import this module, never load the family loader.
        from weather.schema_registry_families import installed_families

        registry = installed_families()
    discovered = scan_schema_literals(paths, registry=registry)
    unregistered_versions = sorted({
        row["version"] for row in discovered if not row["registered"] and not row["excluded"]
    })
    excluded_versions = sorted({
        row["version"] for row in discovered if row["excluded"]
    })
    return {
        "schema_version": SCHEMA_REGISTRY_SCHEMA_VERSION,
        "registered_count": len(registry.schemas),
        "core_registered_count": len(REGISTERED_SCHEMAS),
        "family_registered_count": len(registry.family_schemas),
        "discovered_literal_count": len(discovered),
        "unregistered_version_count": len(unregistered_versions),
        "excluded_version_count": len(excluded_versions),
        "registered_schemas": [asdict(spec) for spec in registry.schemas],
        "excluded_schema_literals": [asdict(item) for item in registry.exclusions],
        "schema_families": [
            {
                "family": family.family,
                "module": family.module,
                "schemas": [spec.name for spec in family.schemas],
                "excluded_versions": [item.version for item in family.exclusions],
            }
            for family in registry.families
        ],
        "family_error_count": len(registry.errors),
        "family_errors": list(registry.errors),
        "unregistered_versions": unregistered_versions,
        "excluded_versions": excluded_versions,
        "discovered_literals": discovered,
    }


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_list(args):
    payload = registry_payload()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for spec in REGISTERED_SCHEMAS:
        print(f"{spec.name}: {spec.version} ({spec.status})")


def cmd_audit(args):
    payload = audit_payload(args.paths)
    if args.out:
        write_json(args.out, payload)
        print(f"Wrote schema registry audit to {args.out}")
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    print(
        "registered={registered_count} discovered={discovered_literal_count} "
        "unregistered_versions={unregistered_version_count} "
        "excluded_versions={excluded_version_count} "
        "family_registered={family_registered_count} family_errors={family_error_count}".format(**payload)
    )
    for error in payload["family_errors"]:
        print(f"family error: {error}")
    if args.strict and (payload["unregistered_version_count"] or payload["family_error_count"]):
        raise SystemExit(1)


def build_parser():
    parser = argparse.ArgumentParser(description="Schema registry and migration audit tooling.")
    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list")
    list_cmd.add_argument("--json", action="store_true")
    list_cmd.set_defaults(func=cmd_list)

    audit_cmd = sub.add_parser("audit")
    audit_cmd.add_argument("--paths", nargs="+", default=["src"])
    audit_cmd.add_argument("--out", default="")
    audit_cmd.add_argument("--strict", action="store_true")
    audit_cmd.set_defaults(func=cmd_audit)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
