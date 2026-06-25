"""Central schema-version registry and migration audit tooling.

The registry is intentionally dependency-free: producer modules import schema
constants from here, while this module never imports producers.
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


def scan_schema_literals(paths=("src",), suffixes=DEFAULT_SCAN_SUFFIXES):
    """Find schema-looking string literals in source files."""
    rows = []
    for path in sorted(set(_iter_scan_files(paths, suffixes=suffixes))):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(lines, start=1):
            for match in SCHEMA_LITERAL_RE.finditer(line):
                version = match.group(1)
                spec = SCHEMAS_BY_VERSION.get(version)
                exclusion = EXCLUDED_SCHEMA_LITERAL_BY_VERSION.get(version)
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


def audit_payload(paths=("src",)) -> dict:
    discovered = scan_schema_literals(paths)
    unregistered_versions = sorted({
        row["version"] for row in discovered if not row["registered"] and not row["excluded"]
    })
    excluded_versions = sorted({
        row["version"] for row in discovered if row["excluded"]
    })
    return {
        "schema_version": SCHEMA_REGISTRY_SCHEMA_VERSION,
        "registered_count": len(REGISTERED_SCHEMAS),
        "discovered_literal_count": len(discovered),
        "unregistered_version_count": len(unregistered_versions),
        "excluded_version_count": len(excluded_versions),
        "registered_schemas": [asdict(spec) for spec in REGISTERED_SCHEMAS],
        "excluded_schema_literals": [asdict(item) for item in EXCLUDED_SCHEMA_LITERALS],
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
        "excluded_versions={excluded_version_count}".format(**payload)
    )
    if args.strict and payload["unregistered_version_count"]:
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
