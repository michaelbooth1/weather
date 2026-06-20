"""Model-variant lifecycle registry helpers."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import REPO_ROOT, config_path

from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("model_variant_registry")
AUDIT_SCHEMA_VERSION = schema_version("model_variant_registry_audit")
DEFAULT_REGISTRY_PATH = config_path() / "model_variant_registry.json"
REQUIRED_ACTIVE_EXPORT_FIELDS = (
    "prediction_function",
    "prediction_mode",
    "export_family",
    "default_export_path",
    "live_runtime",
)


def empty_registry(path=None):
    return {
        "schema_version": SCHEMA_VERSION,
        "path": str(path) if path else None,
        "exists": False,
        "variants": [],
        "by_id": {},
    }


def load_registry(path=DEFAULT_REGISTRY_PATH):
    if path in (None, ""):
        return empty_registry(path)
    path = Path(path)
    if not path.exists():
        return empty_registry(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported model variant registry schema {payload.get('schema_version')!r}"
        )
    variants = payload.get("variants") or []
    by_id = {
        str(row.get("variant_id")): dict(row)
        for row in variants
        if row.get("variant_id")
    }
    output = dict(payload)
    output["path"] = str(path)
    output["exists"] = True
    output["variants"] = variants
    output["by_id"] = by_id
    return output


def registry_entry(registry, variant_id):
    return (registry or {}).get("by_id", {}).get(str(variant_id))


def active_registry_variants(registry):
    return [
        row
        for row in (registry or {}).get("variants") or []
        if row.get("lifecycle") == "active"
        and bool(row.get("active_for_headline", True))
        and "control" not in {str(role) for role in row.get("roles") or []}
    ]


def variant_export_contract(variant):
    contract = dict(variant.get("export_contract") or {})
    for key in (
        "artifact_path",
        "artifact_required",
        "prediction_function",
        "prediction_mode",
        "export_family",
        "default_export_path",
        "postprocess_config_hash",
        "live_runtime",
    ):
        if key in variant and key not in contract:
            contract[key] = variant.get(key)
    contract.setdefault("artifact_required", True)
    contract.setdefault("variant_id", variant.get("variant_id"))
    contract.setdefault("variant_family", variant.get("variant_family"))
    contract.setdefault("track", variant.get("track"))
    return contract


def resolve_registry_path(value):
    if value in (None, ""):
        return None
    value = str(value)
    if "://" in value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def active_export_paths(registry):
    paths = []
    seen = set()
    for variant in active_registry_variants(registry):
        path = variant_export_contract(variant).get("default_export_path")
        if path and str(path) not in seen:
            paths.append(str(path))
            seen.add(str(path))
    return paths


def variant_contract_for_artifact(registry, artifact_path=None, *, prediction_function=None):
    if not artifact_path:
        return None
    resolved_artifact = resolve_registry_path(artifact_path)
    normalized_artifact = resolved_artifact.resolve() if resolved_artifact else None
    for variant in active_registry_variants(registry):
        contract = variant_export_contract(variant)
        if prediction_function and contract.get("prediction_function") != prediction_function:
            continue
        contract_path = resolve_registry_path(contract.get("artifact_path"))
        if not contract_path or not normalized_artifact:
            continue
        try:
            matches = contract_path.resolve() == normalized_artifact
        except OSError:
            matches = contract_path.absolute() == normalized_artifact
        if matches:
            return {**contract, "variant": variant}
    return None


def decorate_variant(metadata, registry=None):
    entry = registry_entry(registry, metadata.get("variant_id")) or {}
    is_control = bool(metadata.get("is_control"))
    lifecycle = entry.get("lifecycle") or ("control" if is_control else "unregistered")
    roles = set(entry.get("roles") or [])
    if is_control:
        roles.add("control")
    if metadata.get("uses_market_features"):
        roles.add("market-informed")
    else:
        roles.add("no-market")
    track = entry.get("track") or (
        "market_informed" if metadata.get("uses_market_features") else "no_market"
    )
    active_for_headline = entry.get("active_for_headline")
    if active_for_headline is None:
        active_for_headline = lifecycle == "active" and not is_control
    return {
        "registry_lifecycle": lifecycle,
        "registry_roles": sorted(roles),
        "registry_track": track,
        "active_for_headline": bool(active_for_headline),
        "registry_roadmap_items": entry.get("roadmap_items") or [],
        "registry_notes": entry.get("notes"),
    }


def registry_summary(variants, registry=None):
    active_registry_ids = [
        row.get("variant_id")
        for row in active_registry_variants(registry or {})
        if row.get("variant_id")
    ]
    reported_ids = {variant.get("variant_id") for variant in variants if variant.get("variant_id")}
    missing_active_ids = sorted(str(variant_id) for variant_id in active_registry_ids if variant_id not in reported_ids)
    lifecycle_counts = Counter(
        variant.get("registry_lifecycle") or "unregistered"
        for variant in variants
    )
    active = [
        variant for variant in variants
        if variant.get("active_for_headline") and not variant.get("is_control")
    ]
    archived = [
        variant for variant in variants
        if variant.get("registry_lifecycle") in {"archived", "smoke", "alpha"}
    ]
    return {
        "path": (registry or {}).get("path"),
        "schema_version": (registry or {}).get("schema_version"),
        "exists": bool((registry or {}).get("exists")),
        "registered_variant_count": len((registry or {}).get("variants") or []),
        "reported_variant_count": len(variants),
        "active_headline_variant_count": len(active),
        "active_headline_variant_ids": [variant.get("variant_id") for variant in active],
        "registered_active_headline_variant_ids": active_registry_ids,
        "missing_active_headline_variant_ids": missing_active_ids,
        "missing_active_headline_variant_count": len(missing_active_ids),
        "archived_or_historical_variant_count": len(archived),
        "unregistered_variant_count": lifecycle_counts.get("unregistered", 0),
        "lifecycle_counts": dict(sorted(lifecycle_counts.items())),
    }


def _utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _check(severity, category, detail, *, variant_id=None, path=None):
    row = {
        "severity": severity,
        "category": category,
        "detail": detail,
    }
    if variant_id is not None:
        row["variant_id"] = variant_id
    if path is not None:
        row["path"] = str(path)
    return row


def _variant_ids_from_json_payload(payload):
    if isinstance(payload, dict):
        for key in ("rows", "predictions", "variant_rows"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        return set()
    return {
        str(row.get("variant_id"))
        for row in payload
        if isinstance(row, dict) and row.get("variant_id")
    }


def _variant_ids_from_evidence_path(path):
    path = Path(path)
    if not path.exists():
        return set()
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        ids = set()
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                payload = json.loads(line)
                if isinstance(payload, dict) and payload.get("variant_id"):
                    ids.add(str(payload.get("variant_id")))
        return ids
    if suffix == ".json":
        return _variant_ids_from_json_payload(json.loads(path.read_text(encoding="utf-8")))
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {
            str(row.get("variant_id"))
            for row in csv.DictReader(handle)
            if row.get("variant_id")
        }


def _evidence_summary(paths):
    ids = set()
    path_rows = []
    for value in paths:
        resolved = resolve_registry_path(value) or Path(value)
        exists = resolved.exists()
        row = {
            "path": str(value),
            "resolved_path": str(resolved),
            "exists": exists,
        }
        if exists:
            stat = resolved.stat()
            row["bytes"] = stat.st_size
            row["modified_at_utc"] = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
            row_ids = _variant_ids_from_evidence_path(resolved)
            row["variant_ids"] = sorted(row_ids)
            ids.update(row_ids)
        else:
            row["variant_ids"] = []
        path_rows.append(row)
    return ids, path_rows


def audit_registry(
    registry_or_path=DEFAULT_REGISTRY_PATH,
    *,
    evidence_paths=None,
    check_paths=True,
    generated_at_utc=None,
):
    registry = load_registry(registry_or_path) if not isinstance(registry_or_path, dict) else registry_or_path
    checks = []
    variants = registry.get("variants") or []
    ids = [str(row.get("variant_id")) for row in variants if row.get("variant_id")]
    counts = Counter(ids)
    for variant_id, count in sorted(counts.items()):
        if count > 1:
            checks.append(_check(
                "error",
                "duplicate_variant_id",
                f"variant_id appears {count} times in the registry",
                variant_id=variant_id,
            ))

    active_variants = active_registry_variants(registry)
    active_ids = sorted(str(row.get("variant_id")) for row in active_variants if row.get("variant_id"))
    contracts = []
    for variant in active_variants:
        variant_id = variant.get("variant_id")
        contract = variant_export_contract(variant)
        contracts.append(contract)
        missing = [field for field in REQUIRED_ACTIVE_EXPORT_FIELDS if not contract.get(field)]
        if contract.get("artifact_required", True) and not contract.get("artifact_path"):
            missing.append("artifact_path")
        if missing:
            checks.append(_check(
                "error",
                "missing_export_contract_fields",
                "active variant is missing export contract field(s): " + ", ".join(sorted(missing)),
                variant_id=variant_id,
            ))
        artifact_path = contract.get("artifact_path")
        resolved_artifact = resolve_registry_path(artifact_path)
        if check_paths and artifact_path and resolved_artifact is not None and not resolved_artifact.exists():
            checks.append(_check(
                "error",
                "missing_artifact_path",
                "configured artifact_path does not exist",
                variant_id=variant_id,
                path=artifact_path,
            ))

    if evidence_paths is None:
        evidence_paths = active_export_paths(registry)
    evidence_ids, evidence_path_rows = _evidence_summary(evidence_paths or [])
    for row in evidence_path_rows:
        if check_paths and not row.get("exists"):
            checks.append(_check(
                "error",
                "missing_export_path",
                "configured default_export_path does not exist",
                path=row.get("path"),
            ))
    missing_evidence_ids = sorted(set(active_ids) - evidence_ids)
    for variant_id in missing_evidence_ids:
        checks.append(_check(
            "error",
            "active_variant_missing_from_evidence",
            "active registry variant did not produce rows in the configured evidence exports",
            variant_id=variant_id,
        ))

    error_count = sum(1 for row in checks if row.get("severity") == "error")
    warning_count = sum(1 for row in checks if row.get("severity") == "warning")
    status = "ERROR" if error_count else ("WARN" if warning_count else "OK")
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or _utc_iso(),
        "status": status,
        "registry": {
            "path": registry.get("path"),
            "exists": bool(registry.get("exists")),
            "schema_version": registry.get("schema_version"),
        },
        "summary": {
            "registered_variant_count": len(variants),
            "active_variant_count": len(active_variants),
            "active_contract_count": len(contracts),
            "evidence_path_count": len(evidence_path_rows),
            "evidence_variant_count": len(evidence_ids),
            "missing_active_variant_count": len(missing_evidence_ids),
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "active_variant_ids": active_ids,
        "evidence_paths": evidence_path_rows,
        "active_contracts": contracts,
        "missing_active_variant_ids": missing_evidence_ids,
        "checks": checks,
    }


def write_audit_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def write_audit_report(path, payload):
    path = Path(path)
    summary = payload.get("summary") or {}
    lines = [
        "# Model Variant Registry Audit",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        "",
        "## Summary",
        "",
        *markdown_table(
            ["Metric", "Value"],
            [
                ["Registered variants", summary.get("registered_variant_count")],
                ["Active variants", summary.get("active_variant_count")],
                ["Active contracts", summary.get("active_contract_count")],
                ["Evidence paths", summary.get("evidence_path_count")],
                ["Evidence variants", summary.get("evidence_variant_count")],
                ["Missing active variants", summary.get("missing_active_variant_count")],
                ["Errors", summary.get("error_count")],
                ["Warnings", summary.get("warning_count")],
            ],
        ),
        "",
        "## Checks",
        "",
    ]
    checks = payload.get("checks") or []
    if checks:
        lines.extend(markdown_table(
            ["Severity", "Category", "Variant", "Path", "Detail"],
            [
                [
                    row.get("severity"),
                    row.get("category"),
                    row.get("variant_id") or "-",
                    row.get("path") or "-",
                    row.get("detail"),
                ]
                for row in checks
            ],
        ))
    else:
        lines.append("- none")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit model-variant registry export contracts and evidence.")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY_PATH))
    parser.add_argument("--evidence", action="append", default=None, help="Evidence CSV/JSON/JSONL path. Repeatable.")
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--report-out", default=None)
    parser.add_argument("--no-path-check", action="store_true")
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args(argv)
    payload = audit_registry(
        args.registry,
        evidence_paths=args.evidence,
        check_paths=not args.no_path_check,
    )
    if args.json_out:
        write_audit_json(args.json_out, payload)
    if args.report_out:
        write_audit_report(args.report_out, payload)
    print(f"Model variant registry audit: {payload['status']}")
    if args.fail_on_error and payload["status"] == "ERROR":
        raise SystemExit(1)
    return payload


if __name__ == "__main__":
    main()
