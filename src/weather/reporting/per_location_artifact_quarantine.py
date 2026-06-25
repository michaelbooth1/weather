"""Per-location model artifact quarantine report.

This report keeps old per-location HGB artifacts out of active promotion
comparisons unless they are registered and retrained under the active feature
schema family.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.artifacts import (
    ARTIFACTS_ROOT,
    DEFAULT_ARTIFACT_REGISTRY_PATH,
    DEFAULT_VARIANT_REGISTRY_PATH,
    build_artifact_registry,
    feature_schema_migration_plan,
)
from weather.model.feature_store import FEATURE_SCHEMA_VERSION
from weather.paths import data_path, relative_to_repo
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("per_location_artifact_quarantine")
DEFAULT_JSON_OUT = data_path() / "backtest" / "per_location_artifact_quarantine.json"
DEFAULT_REPORT_OUT = data_path() / "backtest" / "per_location_artifact_quarantine_report.md"

ACTIVE_REGISTRY_USES = {"active_promoted", "active_shadow"}
PER_LOCATION_HGB_RE = re.compile(r"^feature_model_hgb(?:_(?P<suffix>.+))?\.pkl$")
PER_LOCATION_COEFS_RE = re.compile(r"^feature_model_coefs(?:_(?P<suffix>.+))?\.json$")
SCHEMA_VERSION_RE = re.compile(r"_v(?P<major>\d+)(?:\.(?P<minor>\d+))?")


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _market_from_suffix(suffix: str | None) -> str | None:
    if suffix in (None, ""):
        return "toronto"
    suffix = str(suffix)
    if suffix.startswith(("f_pooled", "all_pooled", "pooled")):
        return None
    return suffix


def _per_location_kind(row: dict[str, Any]) -> tuple[str | None, str | None]:
    name = Path(str(row.get("path") or row.get("artifact_id") or "")).name
    hgb_match = PER_LOCATION_HGB_RE.match(name)
    if hgb_match:
        return "hgb_model", _market_from_suffix(hgb_match.group("suffix"))
    coefs_match = PER_LOCATION_COEFS_RE.match(name)
    if coefs_match:
        return "coefs_model", _market_from_suffix(coefs_match.group("suffix"))
    return None, None


def _schema_major(version: str | None) -> int | None:
    if not version:
        return None
    match = SCHEMA_VERSION_RE.search(str(version))
    if not match:
        return None
    return int(match.group("major"))


def _schema_status(
    version: str | None,
    active_version: str,
    migration: dict[str, Any] | None = None,
) -> str:
    migration = migration or {}
    if migration.get("migration_status") == "migrated":
        return "migrated_schema"
    if migration.get("migration_status") == "current":
        return "active_schema"
    major = _schema_major(version)
    active_major = _schema_major(active_version)
    if major is None:
        return "missing_schema"
    if active_major is not None and major < active_major:
        return "stale_schema"
    return "active_schema"


def _first_schema(rows: list[dict[str, Any]]) -> str | None:
    for row in rows:
        if row.get("feature_schema_version"):
            return row.get("feature_schema_version")
    return None


def _reasons(row: dict[str, Any], schema_status: str, active_candidate: bool) -> list[str]:
    reasons = []
    registry_use = row.get("registry_use")
    if registry_use == "unregistered_runtime_artifact":
        reasons.append("unregistered runtime artifact")
    elif registry_use not in ACTIVE_REGISTRY_USES:
        reasons.append(f"registry_use={registry_use or 'missing'} is not active")
    if schema_status == "stale_schema":
        reasons.append("feature schema predates active feature family")
    elif schema_status == "missing_schema":
        reasons.append("feature schema is missing from artifact metadata")
    if not reasons and not active_candidate:
        reasons.append("historical-only artifact")
    return reasons


def _artifact_rows(registry: dict[str, Any], active_feature_schema_version: str) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in registry.get("artifacts") or []:
        kind, market_id = _per_location_kind(row)
        if not kind or not market_id:
            continue
        groups[market_id][kind].append(row)

    output = []
    for market_id, by_kind in sorted(groups.items()):
        paired_schema = _first_schema(by_kind.get("coefs_model") or [])
        for kind in ("hgb_model", "coefs_model"):
            for row in by_kind.get(kind) or []:
                feature_schema = row.get("feature_schema_version") or paired_schema
                migration = feature_schema_migration_plan(
                    feature_schema,
                    active_feature_schema_version,
                    stable_feature_names=True,
                )
                schema_status = _schema_status(
                    feature_schema,
                    active_feature_schema_version,
                    migration,
                )
                active_candidate = row.get("registry_use") in ACTIVE_REGISTRY_USES
                promotable = (
                    active_candidate
                    and migration.get("migration_status") in {"current", "migrated"}
                    and migration.get("effective_feature_schema_version") == active_feature_schema_version
                )
                reasons = _reasons(row, schema_status, active_candidate)
                if promotable:
                    disposition = "active_candidate"
                elif active_candidate:
                    disposition = "active_candidate_blocked"
                else:
                    disposition = "historical_only"
                output.append({
                    "market_id": market_id,
                    "artifact_kind": kind,
                    "path": row.get("path"),
                    "artifact_id": row.get("artifact_id"),
                    "registry_use": row.get("registry_use"),
                    "variant_refs": row.get("variant_refs") or [],
                    "feature_schema_version": feature_schema,
                    "effective_feature_schema_version": migration.get("effective_feature_schema_version"),
                    "metadata_feature_schema_version": row.get("feature_schema_version"),
                    "paired_feature_schema_version": paired_schema,
                    "active_feature_schema_version": active_feature_schema_version,
                    "schema_status": schema_status,
                    "migration_status": migration.get("migration_status"),
                    "migration_classification": migration.get("classification"),
                    "migration_action": migration.get("action"),
                    "migration_reason": migration.get("reason"),
                    "schema_migration": migration,
                    "active_candidate": active_candidate,
                    "promotable": promotable,
                    "disposition": disposition,
                    "reasons": reasons,
                })
    return output


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    disposition_counts = Counter(row["disposition"] for row in rows)
    schema_counts = Counter(row["schema_status"] for row in rows)
    migration_counts = Counter(row.get("migration_status") or "unknown" for row in rows)
    migration_class_counts = Counter(row.get("migration_classification") or "unknown" for row in rows)
    registry_counts = Counter(row.get("registry_use") or "missing" for row in rows)
    active_violations = [
        row for row in rows
        if row.get("active_candidate") and not row.get("promotable")
    ]
    return {
        "per_location_artifact_count": len(rows),
        "historical_only_count": disposition_counts.get("historical_only", 0),
        "active_candidate_count": sum(1 for row in rows if row.get("active_candidate")),
        "active_candidate_violation_count": len(active_violations),
        "stale_schema_count": schema_counts.get("stale_schema", 0),
        "missing_schema_count": schema_counts.get("missing_schema", 0),
        "migrated_schema_count": schema_counts.get("migrated_schema", 0),
        "migratable_artifact_count": migration_class_counts.get("migratable", 0),
        "unrecoverable_artifact_count": migration_class_counts.get("unrecoverable", 0),
        "disposition_counts": dict(sorted(disposition_counts.items())),
        "schema_status_counts": dict(sorted(schema_counts.items())),
        "migration_status_counts": dict(sorted(migration_counts.items())),
        "migration_classification_counts": dict(sorted(migration_class_counts.items())),
        "registry_use_counts": dict(sorted(registry_counts.items())),
    }


def build_payload(
    *,
    artifact_registry_path: str | Path = DEFAULT_ARTIFACT_REGISTRY_PATH,
    artifact_root: str | Path = ARTIFACTS_ROOT,
    variant_registry_path: str | Path | None = DEFAULT_VARIANT_REGISTRY_PATH,
    active_feature_schema_version: str = FEATURE_SCHEMA_VERSION,
    generated_at_utc: str | None = None,
    registry_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    registry = registry_payload
    registry_path = Path(artifact_registry_path)
    if registry is None:
        registry = read_json(registry_path)
    if not registry:
        registry = build_artifact_registry(
            root=artifact_root,
            variant_registry_path=variant_registry_path,
        )
    rows = _artifact_rows(registry, active_feature_schema_version)
    summary = _summary(rows)
    active_violations = [
        row for row in rows
        if row.get("active_candidate") and not row.get("promotable")
    ]
    status = "FAIL" if active_violations else "PASS"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "status": status,
        "artifact_registry_path": relative_to_repo(registry_path),
        "artifact_root": registry.get("artifact_root") or relative_to_repo(artifact_root),
        "active_feature_schema_version": active_feature_schema_version,
        "summary": summary,
        "active_candidate_violations": active_violations,
        "artifacts": rows,
        "policy": (
            "Per-location HGB artifacts are non-promotable unless they are active "
            "registry variants and use, or can be deterministically migrated to, "
            "the active feature schema family."
        ),
    }


def render_report(payload: dict[str, Any], *, artifact_limit: int = 80) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Per-Location Artifact Schema Quarantine",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        f"Active feature schema: `{payload.get('active_feature_schema_version')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Per-location artifacts", summary.get("per_location_artifact_count", 0)],
            ["Historical-only artifacts", summary.get("historical_only_count", 0)],
            ["Active candidate artifacts", summary.get("active_candidate_count", 0)],
            ["Active candidate violations", summary.get("active_candidate_violation_count", 0)],
            ["Stale-schema artifacts", summary.get("stale_schema_count", 0)],
            ["Missing-schema artifacts", summary.get("missing_schema_count", 0)],
            ["Migrated-schema artifacts", summary.get("migrated_schema_count", 0)],
            ["Migratable artifacts", summary.get("migratable_artifact_count", 0)],
            ["Unrecoverable artifacts", summary.get("unrecoverable_artifact_count", 0)],
        ],
    )

    violations = payload.get("active_candidate_violations") or []
    lines += ["", "## Active Candidate Violations", ""]
    if violations:
        lines += markdown_table(
            ["Market", "Kind", "Disposition", "Schema", "Migration", "Registry use", "Path", "Reasons"],
            [
                [
                    row.get("market_id"),
                    row.get("artifact_kind"),
                    row.get("disposition"),
                    row.get("feature_schema_version") or "-",
                    row.get("migration_status") or "-",
                    row.get("registry_use") or "-",
                    row.get("path"),
                    "; ".join(row.get("reasons") or []),
                ]
                for row in violations
            ],
        )
    else:
        lines.append("No stale or unregistered per-location artifact is active in promotion.")

    rows = payload.get("artifacts") or []
    lines += ["", "## Historical-Only / Quarantined Artifacts", ""]
    lines += markdown_table(
        ["Market", "Kind", "Disposition", "Schema", "Migration", "Registry use", "Path", "Reasons"],
        [
            [
                row.get("market_id"),
                row.get("artifact_kind"),
                row.get("disposition"),
                row.get("feature_schema_version") or "-",
                row.get("migration_status") or "-",
                row.get("registry_use") or "-",
                row.get("path"),
                "; ".join(row.get("reasons") or []),
            ]
            for row in rows[:artifact_limit]
        ],
    )
    if len(rows) > artifact_limit:
        lines.append("")
        lines.append(f"Report truncated to {artifact_limit} of {len(rows)} artifacts.")
    return "\n".join(lines) + "\n"


def write_outputs(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_JSON_OUT,
    report_out: str | Path = DEFAULT_REPORT_OUT,
) -> tuple[Path, Path]:
    json_path = Path(json_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path = Path(report_out)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit stale per-location model artifacts.")
    parser.add_argument("--artifact-root", default=str(ARTIFACTS_ROOT))
    parser.add_argument("--artifact-registry", default=str(DEFAULT_ARTIFACT_REGISTRY_PATH))
    parser.add_argument("--variant-registry", default=str(DEFAULT_VARIANT_REGISTRY_PATH))
    parser.add_argument("--active-feature-schema-version", default=FEATURE_SCHEMA_VERSION)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--fail-on-active-violation", action="store_true")
    args = parser.parse_args(argv)

    payload = build_payload(
        artifact_registry_path=args.artifact_registry,
        artifact_root=args.artifact_root,
        variant_registry_path=args.variant_registry,
        active_feature_schema_version=args.active_feature_schema_version,
    )
    json_path, report_path = write_outputs(payload, args.json_out, args.report_out)
    print(f"Per-location artifact quarantine: {payload['status']}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    if args.fail_on_active_violation and payload["status"] != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
