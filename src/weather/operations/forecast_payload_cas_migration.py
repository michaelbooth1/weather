"""Inventory-only migration and partial reachability scan for the shared CAS.

This command intentionally has no apply, rewrite, garbage-collection, or delete
mode.  It proves what *could* be migrated while legacy evidence remains intact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from weather.collection.forecast_payload_cas import (
    ForecastPayloadCASIntegrityError,
    SharedForecastPayloadCAS,
    manifest_extraction_identity,
    resolve_forecast_payload_bytes,
    shared_payload_ref,
)
from weather.paths import data_path
from weather.sources.nbm_probabilistic_tmax import replay_nbp_shared_payload


SCHEMA_VERSION = "forecast_payload_cas_migration_dry_run_v0.1"
DEFAULT_SNAPSHOT_ROOT = data_path("snapshots")
DEFAULT_SHARED_CAS_ROOT = data_path("forecast_payload_cas")
DEFAULT_JSON_OUT = data_path("backtest", "forecast_payload_cas_migration_dry_run.json")
DEFAULT_REPORT_OUT = data_path(
    "backtest", "forecast_payload_cas_migration_dry_run_report.md"
)


def _iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                yield line_number, {"_read_error": f"invalid_json:{exc.msg}"}
                continue
            if not isinstance(row, dict):
                yield line_number, {"_read_error": "row_not_object"}
                continue
            yield line_number, row


def _legacy_candidate(
    row: dict[str, Any],
    *,
    manifest_path: Path,
    line_number: int,
    shared_cas: SharedForecastPayloadCAS,
) -> dict[str, Any]:
    base = {
        "candidate_kind": "legacy_migration_candidate",
        "manifest_path": str(manifest_path),
        "line_number": line_number,
        "snapshot_id": row.get("snapshot_id"),
        "event_slug": row.get("event_slug") or manifest_path.parent.name,
        "source": row.get("source"),
        "legacy_payload_hash": row.get("payload_hash"),
        "legacy_payload_path": row.get("raw_payload_path"),
    }
    issues: list[str] = []
    try:
        wrapper_bytes = resolve_forecast_payload_bytes(
            row,
            event_folder=manifest_path.parent,
        )
    except (ForecastPayloadCASIntegrityError, OSError, ValueError) as exc:
        return {
            **base,
            "status": "BLOCK",
            "issues": [f"legacy_hash_or_restore_failed:{type(exc).__name__}:{exc}"],
        }
    try:
        wrapper = json.loads(wrapper_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            **base,
            "status": "BLOCK",
            "issues": [f"legacy_payload_invalid_json:{type(exc).__name__}:{exc}"],
        }
    if not isinstance(wrapper, dict):
        issues.append("legacy_payload_not_object")
        text = None
    else:
        text = wrapper.get("text")
    if not isinstance(text, str):
        issues.append("nbm_national_text_missing")
        body_bytes = b""
    else:
        body_bytes = text.encode("utf-8")
    digest = hashlib.sha256(body_bytes).hexdigest() if body_bytes else ""
    identity = {
        "station_id": (wrapper or {}).get("station_id") if isinstance(wrapper, dict) else None,
        "target_date": (wrapper or {}).get("target_date") if isinstance(wrapper, dict) else None,
    }
    replay_status = "NOT_RUN"
    if not issues:
        try:
            replayed = replay_nbp_shared_payload(
                body_bytes,
                identity,
                source_url=(wrapper or {}).get("source_url"),
                fetched_at=(wrapper or {}).get("fetched_at"),
            )
            if (
                replayed.get("station_id") != identity["station_id"]
                or replayed.get("target_date") != identity["target_date"]
            ):
                raise ValueError("replayed extraction identity changed")
            replay_status = "PASS"
        except Exception as exc:  # noqa: BLE001 - dry-run report retains exact failure
            issues.append(f"replay_proof_failed:{type(exc).__name__}:{exc}")
            replay_status = "BLOCK"
    shared_path = shared_cas.path_for(digest) if digest else None
    shared_status = "ABSENT"
    if shared_path is not None and (shared_path.exists() or shared_path.is_symlink()):
        try:
            shared_cas.verify(digest, expected_bytes=len(body_bytes))
            shared_status = "VERIFIED"
        except ForecastPayloadCASIntegrityError as exc:
            shared_status = "CORRUPT"
            issues.append(f"shared_blob_invalid:{exc}")
    return {
        **base,
        "status": "PASS" if not issues else "BLOCK",
        "issues": issues,
        "legacy_payload_bytes": len(wrapper_bytes),
        "shared_payload_hash": digest or None,
        "shared_payload_bytes": len(body_bytes),
        "shared_payload_ref": shared_payload_ref(digest) if digest else None,
        "shared_payload_path": str(shared_path) if shared_path is not None else None,
        "shared_blob_status": shared_status,
        "extraction_identity": identity,
        "restore_hash_status": "PASS",
        "replay_status": replay_status,
        "would_copy": bool(shared_status == "ABSENT" and not issues),
        "would_rewrite_manifest": False,
        "would_delete_legacy_blob": False,
    }


def _shared_reference_candidate(
    row: dict[str, Any],
    *,
    manifest_path: Path,
    line_number: int,
    shared_cas: SharedForecastPayloadCAS,
) -> dict[str, Any]:
    base = {
        "candidate_kind": "active_shared_reference",
        "manifest_path": str(manifest_path),
        "line_number": line_number,
        "snapshot_id": row.get("snapshot_id"),
        "event_slug": row.get("event_slug") or manifest_path.parent.name,
        "market_id": row.get("market_id"),
        "source": row.get("source"),
        "payload_hash": row.get("payload_hash"),
        "payload_ref": row.get("payload_ref"),
        "raw_payload_path": row.get("raw_payload_path"),
    }
    issues: list[str] = []
    payload_bytes = b""
    identity: dict[str, str] | None = None
    replay_status = "NOT_RUN"
    try:
        if row.get("schema_version") != "forecast_payload_manifest_v2":
            raise ForecastPayloadCASIntegrityError(
                "active shared reference requires forecast_payload_manifest_v2"
            )
        if not str(row.get("request_key") or "").strip():
            raise ForecastPayloadCASIntegrityError("shared request_key missing")
        if not str(row.get("cycle_key") or "").strip():
            raise ForecastPayloadCASIntegrityError("shared cycle_key missing")
        payload_bytes = resolve_forecast_payload_bytes(
            row,
            shared_cas_root=shared_cas.root,
        )
        digest = str(row.get("payload_hash") or "")
        declared_path = Path(str(row.get("raw_payload_path") or ""))
        expected_path = shared_cas.path_for(digest)
        if (
            not declared_path.is_absolute()
            or declared_path.resolve() != expected_path.resolve()
        ):
            raise ForecastPayloadCASIntegrityError(
                "shared payload path does not match the inventoried CAS root"
            )
        identity = manifest_extraction_identity(row)
        if row.get("source") != "nbm_probabilistic_tmax":
            raise ForecastPayloadCASIntegrityError(
                "shared replay verifier is not registered for source"
            )
        replayed = replay_nbp_shared_payload(
            payload_bytes,
            identity,
            source_url=row.get("source_url"),
            fetched_at=row.get("fetched_at"),
        )
        if (
            replayed.get("station_id") != identity["station_id"]
            or replayed.get("target_date") != identity["target_date"]
            or (
                row.get("target_date")
                and row.get("target_date") != identity["target_date"]
            )
        ):
            raise ForecastPayloadCASIntegrityError(
                "shared payload replay identity changed"
            )
        replay_status = "PASS"
    except (ForecastPayloadCASIntegrityError, OSError, TypeError, ValueError) as exc:
        issues.append(f"shared_reference_verification_failed:{type(exc).__name__}:{exc}")
        replay_status = "BLOCK"

    return {
        **base,
        "status": "PASS" if not issues else "BLOCK",
        "issues": issues,
        "shared_payload_bytes": len(payload_bytes),
        "shared_blob_status": "VERIFIED" if not issues else "BLOCK",
        "extraction_identity": identity,
        "restore_hash_status": "PASS" if not issues else "BLOCK",
        "replay_status": replay_status,
        "would_copy": False,
        "would_rewrite_manifest": False,
        "would_delete_legacy_blob": False,
    }


def build_migration_dry_run(
    *,
    snapshot_root: str | Path = DEFAULT_SNAPSHOT_ROOT,
    shared_cas_root: str | Path = DEFAULT_SHARED_CAS_ROOT,
) -> dict[str, Any]:
    snapshot_root = Path(snapshot_root)
    shared_cas = SharedForecastPayloadCAS(shared_cas_root)
    candidates: list[dict[str, Any]] = []
    manifest_error_count = 0
    active_shared_digests: set[str] = set()
    manifest_paths = sorted(snapshot_root.rglob("forecast_payloads.jsonl")) if snapshot_root.exists() else []
    for manifest_path in manifest_paths:
        for line_number, row in _iter_jsonl(manifest_path):
            if row.get("_read_error"):
                manifest_error_count += 1
                candidates.append({
                    "manifest_path": str(manifest_path),
                    "line_number": line_number,
                    "status": "BLOCK",
                    "issues": [row["_read_error"]],
                })
                continue
            if row.get("payload_storage_scope") == "shared_market_invariant":
                candidate = _shared_reference_candidate(
                    row,
                    manifest_path=manifest_path,
                    line_number=line_number,
                    shared_cas=shared_cas,
                )
                candidates.append(candidate)
                if candidate.get("status") == "PASS":
                    active_shared_digests.add(
                        str(candidate.get("payload_hash") or "")
                    )
                continue
            if row.get("source") != "nbm_probabilistic_tmax":
                continue
            candidates.append(
                _legacy_candidate(
                    row,
                    manifest_path=manifest_path,
                    line_number=line_number,
                    shared_cas=shared_cas,
                )
            )

    legacy_rows = [
        row
        for row in candidates
        if row.get("candidate_kind") == "legacy_migration_candidate"
    ]
    valid = [
        row
        for row in legacy_rows
        if row.get("status") == "PASS"
    ]
    shared_rows = [
        row
        for row in candidates
        if row.get("candidate_kind") == "active_shared_reference"
    ]
    unique_payloads: dict[str, int] = {}
    for row in valid:
        digest = row.get("shared_payload_hash")
        if digest:
            unique_payloads.setdefault(digest, int(row.get("shared_payload_bytes") or 0))
    logical_bytes = sum(int(row.get("shared_payload_bytes") or 0) for row in valid)
    projected_physical_bytes = sum(unique_payloads.values())

    physical_blobs = sorted(shared_cas.root.rglob("*.blob")) if shared_cas.root.exists() else []
    physical_digests = {path.stem for path in physical_blobs if len(path.stem) == 64}
    unreferenced_within_scanned_scope = sorted(
        physical_digests - active_shared_digests
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "inventory_dry_run",
        "inventory_scope": "snapshot_forecast_payload_jsonl_only",
        "authoritative_for_garbage_collection": False,
        "mutation_performed": False,
        "manifest_rewrite_enabled": False,
        "garbage_collection_enabled": False,
        "deletion_enabled": False,
        "snapshot_root": str(snapshot_root),
        "shared_cas_root": str(shared_cas.root),
        "summary": {
            "manifest_count": len(manifest_paths),
            "inventory_row_count": len(candidates),
            "candidate_row_count": len(legacy_rows),
            "verified_candidate_row_count": len(valid),
            "blocked_candidate_row_count": sum(
                1 for row in legacy_rows if row.get("status") != "PASS"
            ),
            "manifest_error_count": manifest_error_count,
            "shared_reference_row_count": len(shared_rows),
            "verified_shared_reference_row_count": sum(
                1 for row in shared_rows if row.get("status") == "PASS"
            ),
            "blocked_shared_reference_row_count": sum(
                1 for row in shared_rows if row.get("status") != "PASS"
            ),
            "unique_shared_payload_count": len(unique_payloads),
            "logical_referenced_bytes": logical_bytes,
            "projected_physical_bytes": projected_physical_bytes,
            "projected_avoided_bytes": max(0, logical_bytes - projected_physical_bytes),
            "active_shared_reference_count": len(active_shared_digests),
            "physical_shared_blob_count": len(physical_digests),
            "unreferenced_within_scanned_scope_observation_count": len(
                unreferenced_within_scanned_scope
            ),
        },
        "reachability": {
            "status": "PARTIAL_INVENTORY_ONLY",
            "scope": "snapshot_forecast_payload_jsonl_only",
            "authoritative_for_garbage_collection": False,
            "verified_active_shared_digests": sorted(active_shared_digests),
            "unreferenced_within_scanned_scope_observations": (
                unreferenced_within_scanned_scope
            ),
            "delete_candidates": [],
            "note": (
                "This scan is not global reachability. Unreferenced values are "
                "non-authoritative observations only; deletion remains disabled."
            ),
        },
        "candidates": candidates,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    return "\n".join([
        "# Shared Forecast Payload CAS Migration Dry Run",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        "",
        (
            "This report is partial inventory only. It did not copy, rewrite, "
            "garbage-collect, or delete evidence."
        ),
        "",
        f"- Inventory scope: {payload.get('inventory_scope')}",
        (
            "- Authoritative for garbage collection: "
            f"{payload.get('authoritative_for_garbage_collection')}"
        ),
        f"- Candidate manifest rows: {summary.get('candidate_row_count', 0)}",
        f"- Verified candidates: {summary.get('verified_candidate_row_count', 0)}",
        f"- Blocked candidates: {summary.get('blocked_candidate_row_count', 0)}",
        (
            "- Verified active shared-reference rows: "
            f"{summary.get('verified_shared_reference_row_count', 0)}"
        ),
        (
            "- Blocked shared-reference rows: "
            f"{summary.get('blocked_shared_reference_row_count', 0)}"
        ),
        f"- Unique shared payloads: {summary.get('unique_shared_payload_count', 0)}",
        f"- Logical referenced bytes: {summary.get('logical_referenced_bytes', 0)}",
        f"- Projected physical bytes: {summary.get('projected_physical_bytes', 0)}",
        f"- Projected avoided bytes: {summary.get('projected_avoided_bytes', 0)}",
        (
            "- Unreferenced within scanned scope (non-authoritative, no deletion): "
            f"{summary.get('unreferenced_within_scanned_scope_observation_count', 0)}"
        ),
        "",
    ])


def _write_text(path: str | Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Inventory legacy NBM payloads for a future additive shared-CAS migration."
    )
    parser.add_argument("--snapshot-root", default=str(DEFAULT_SNAPSHOT_ROOT))
    parser.add_argument("--shared-cas-root", default=str(DEFAULT_SHARED_CAS_ROOT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    args = parser.parse_args(argv)
    payload = build_migration_dry_run(
        snapshot_root=args.snapshot_root,
        shared_cas_root=args.shared_cas_root,
    )
    _write_text(args.json_out, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    _write_text(args.report_out, render_markdown(payload))
    print(json.dumps({"status": "ok", "summary": payload["summary"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
