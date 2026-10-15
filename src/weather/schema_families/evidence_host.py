"""Evidence host (Data Layer v2 S4) schemas: journal, seals, status, receipts, identity, config."""

from __future__ import annotations

from weather.schema_registry_types import SchemaSpec

_OWNER_DOC = "docs/operations/EVIDENCE_HOST.md"

SCHEMAS = (
    SchemaSpec("evidence_journal", "evidence_journal_v1", "weather.evidence.journal", "active",
               "PL-1 journal row: change-only body rows, heartbeat, cap, gap, guard, warn, pause and "
               f"identity rows of one evidence family ({_OWNER_DOC})."),
    SchemaSpec("evidence_segment_manifest", "evidence_segment_manifest_v1", "weather.evidence.journal", "active",
               "Sealed segment manifest: sha256, bytes, records and verified gzip hash per partition file."),
    SchemaSpec("evidence_day_seal", "evidence_day_seal_v1", "weather.evidence.journal", "active",
               "Daily seal over a family's segment manifests, chained by prev_seal_sha256."),
    SchemaSpec("evidence_family_status", "evidence_family_status_v1", "weather.evidence.telemetry", "active",
               "PL-5 throttled per-family child status: counters, peak memory, pauses, running-vs-disk "
               "code identity."),
    SchemaSpec("evidence_family_ledger", "evidence_family_ledger_v1", "weather.evidence.telemetry", "active",
               "PL-5 daily per-family ledger row written at each day seal."),
    SchemaSpec("evidence_host_status", "evidence_host_status_v1", "weather.evidence.host", "active",
               "PL-6 supervisor status: children, restarts, cap kills, disabled families."),
    SchemaSpec("evidence_kill_receipt", "evidence_kill_receipt_v1", "weather.evidence.host", "active",
               "PL-6 receipt for a child the Job commit cap stopped."),
    SchemaSpec("evidence_code_identity", "evidence_code_identity_v1", "weather.evidence.code_identity", "active",
               "PL-4 code/config identity manifest: repo path to git blob sha1 of the loaded files."),
    SchemaSpec("evidence_host_config", "evidence_host_config_v1", "weather.evidence.config", "active",
               "config/evidence_host.json: families, channels, caps, budgets and station maps."),
)
