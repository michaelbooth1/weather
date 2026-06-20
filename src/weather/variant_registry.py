"""Shared model-variant registry helpers.

The durable registry is configuration, not reporting state. This facade keeps
collection and calibration callers from depending on the reporting package
while preserving the established implementation and CLI under
``weather.reporting.variant_registry``.
"""

from __future__ import annotations

from weather.reporting.variant_registry import (
    AUDIT_SCHEMA_VERSION,
    DEFAULT_REGISTRY_PATH,
    REQUIRED_ACTIVE_EXPORT_FIELDS,
    SCHEMA_VERSION,
    active_export_paths,
    active_registry_variants,
    audit_registry,
    decorate_variant,
    empty_registry,
    load_registry,
    main,
    registry_entry,
    registry_summary,
    resolve_registry_path,
    variant_contract_for_artifact,
    variant_export_contract,
    write_audit_json,
    write_audit_report,
)

__all__ = [
    "AUDIT_SCHEMA_VERSION",
    "DEFAULT_REGISTRY_PATH",
    "REQUIRED_ACTIVE_EXPORT_FIELDS",
    "SCHEMA_VERSION",
    "active_export_paths",
    "active_registry_variants",
    "audit_registry",
    "decorate_variant",
    "empty_registry",
    "load_registry",
    "main",
    "registry_entry",
    "registry_summary",
    "resolve_registry_path",
    "variant_contract_for_artifact",
    "variant_export_contract",
    "write_audit_json",
    "write_audit_report",
]
