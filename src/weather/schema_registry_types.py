"""Shared schema registry record types."""

from __future__ import annotations

from dataclasses import dataclass


SCHEMA_REGISTRY_SCHEMA_VERSION = "schema_registry_v0.1"


@dataclass(frozen=True)
class SchemaSpec:
    name: str
    version: str
    owner: str
    status: str
    description: str = ""
    supersedes: tuple[str, ...] = ()
    migration_notes: str = ""


@dataclass(frozen=True)
class SchemaLiteralExclusion:
    version: str
    owner: str
    classification: str
    reason: str
