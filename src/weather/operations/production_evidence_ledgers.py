"""Append-only production evidence ledgers for Item 321 shadow gates.

The ledgers record already-frozen evidence. They never run capture, replay,
training, daily refresh, nightly retraining, promotion, or rollback.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from weather.io import acquire_writer_lock, release_writer_lock, write_json_atomic
from weather.paths import data_path
from weather.release_artifacts import canonical_payload_sha256, sha256_file
from weather.schema_registry import schema_version


CLEAN_DAY_SCHEMA_VERSION = schema_version("clean_day_ledger")
UNATTENDED_SCHEMA_VERSION = schema_version("unattended_cycle_ledger")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_CLEAN_DAY_JSONL = DEFAULT_BACKTEST_ROOT / "clean_day_ledger.jsonl"
DEFAULT_CLEAN_DAY_JSON = DEFAULT_BACKTEST_ROOT / "clean_day_ledger.json"
DEFAULT_CLEAN_DAY_MD = DEFAULT_BACKTEST_ROOT / "clean_day_ledger.md"
DEFAULT_UNATTENDED_JSONL = DEFAULT_BACKTEST_ROOT / "unattended_cycle_ledger.jsonl"
DEFAULT_UNATTENDED_JSON = DEFAULT_BACKTEST_ROOT / "unattended_cycle_ledger.json"
DEFAULT_UNATTENDED_MD = DEFAULT_BACKTEST_ROOT / "unattended_cycle_ledger.md"
DEFAULT_FLEET = DEFAULT_BACKTEST_ROOT / "fleet_observability.json"
DEFAULT_STAGE_A = DEFAULT_BACKTEST_ROOT / "daily_refresh_settlement_truth_manifest.json"
DEFAULT_STAGE_B = DEFAULT_BACKTEST_ROOT / "daily_refresh_evidence_learning_manifest.json"
DEFAULT_NIGHTLY = DEFAULT_BACKTEST_ROOT / "nightly_retrain_status.json"
ZERO_HASH = ""
TORONTO = ZoneInfo("America/Toronto")


class ProductionEvidenceLedgerError(RuntimeError):
    """The append-only ledger contract could not be verified or extended."""


def _utc_now(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _read_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise ProductionEvidenceLedgerError(f"required evidence does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionEvidenceLedgerError(f"invalid JSON evidence {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProductionEvidenceLedgerError(f"evidence root must be an object: {path}")
    return payload


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _field(payload: Mapping[str, Any], *path: str) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and abs(parsed) != float("inf") else None


def _source_record(path: str | Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(path)
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": (
            payload.get("generated_at_utc")
            or payload.get("completed_at_utc")
            or payload.get("finished_at_utc")
        ),
        "target_date": (
            payload.get("target_date")
            or _field(payload, "clean_active_day_countability", "target_date")
            or _field(payload, "settled_day_freshness", "target_date")
        ),
    }


def _release_identity(payload: Mapping[str, Any]) -> tuple[str, str]:
    nested = payload.get("release_identity")
    nested = nested if isinstance(nested, Mapping) else {}
    release_id = str(payload.get("release_id") or nested.get("release_id") or "").strip()
    manifest_hash = str(
        payload.get("release_manifest_sha256")
        or payload.get("manifest_sha256")
        or nested.get("release_manifest_sha256")
        or nested.get("manifest_sha256")
        or ""
    ).strip()
    return release_id, manifest_hash


def _valid_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text.lower())


def _blocker(blockers: list[dict[str, Any]], code: str, field: str, actual: Any, expected: str) -> None:
    blockers.append({
        "code": code,
        "field": field,
        "actual": actual,
        "expected": expected,
    })


def _require_equal(
    blockers: list[dict[str, Any]],
    payload: Mapping[str, Any],
    path: tuple[str, ...],
    expected: Any,
    code: str,
) -> None:
    actual = _field(payload, *path)
    if actual != expected:
        _blocker(blockers, code, ".".join(path), actual, repr(expected))


def _require_number(
    blockers: list[dict[str, Any]],
    payload: Mapping[str, Any],
    path: tuple[str, ...],
    predicate,
    expected: str,
    code: str,
) -> None:
    actual = _field(payload, *path)
    parsed = _number(actual)
    if parsed is None or not predicate(parsed):
        _blocker(blockers, code, ".".join(path), actual, expected)


def _record_content(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in entry.items()
        if key not in {
            "sequence",
            "previous_entry_sha256",
            "entry_sha256",
            "record_sha256",
            "recorded_at_utc",
        }
    }


def _entry_hash(entry: Mapping[str, Any]) -> str:
    return canonical_payload_sha256(entry, omit=("entry_sha256",))


def _read_entries(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ProductionEvidenceLedgerError(
                    f"invalid ledger JSON at {path}:{line_number}: {exc}"
                ) from exc
            if not isinstance(row, dict):
                raise ProductionEvidenceLedgerError(
                    f"ledger row must be an object at {path}:{line_number}"
                )
            rows.append(row)
    return rows


def verify_chain(entries_or_path: Iterable[Mapping[str, Any]] | str | Path) -> dict[str, Any]:
    entries = (
        _read_entries(entries_or_path)
        if isinstance(entries_or_path, (str, Path))
        else [dict(row) for row in entries_or_path]
    )
    errors = []
    previous_hash = ZERO_HASH
    seen_keys = set()
    for expected_sequence, entry in enumerate(entries, start=1):
        entry_key = str(entry.get("entry_key") or "")
        if entry.get("sequence") != expected_sequence:
            errors.append({
                "code": "sequence_mismatch",
                "sequence": expected_sequence,
                "actual": entry.get("sequence"),
            })
        if entry.get("previous_entry_sha256") != previous_hash:
            errors.append({
                "code": "previous_hash_mismatch",
                "sequence": expected_sequence,
                "actual": entry.get("previous_entry_sha256"),
                "expected": previous_hash,
            })
        expected_record_hash = canonical_payload_sha256(_record_content(entry))
        if entry.get("record_sha256") != expected_record_hash:
            errors.append({
                "code": "record_hash_mismatch",
                "sequence": expected_sequence,
            })
        expected_entry_hash = _entry_hash(entry)
        if entry.get("entry_sha256") != expected_entry_hash:
            errors.append({
                "code": "entry_hash_mismatch",
                "sequence": expected_sequence,
            })
        if not entry_key or entry_key in seen_keys:
            errors.append({
                "code": "duplicate_or_missing_entry_key",
                "sequence": expected_sequence,
                "entry_key": entry_key,
            })
        seen_keys.add(entry_key)
        previous_hash = str(entry.get("entry_sha256") or "")
    return {
        "status": "PASS" if not errors else "BLOCK",
        "entry_count": len(entries),
        "entry_chain_sha256": previous_hash,
        "errors": errors,
    }


def append_entry(
    path: str | Path,
    entry: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Append a verified entry or return an idempotent no-op."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = acquire_writer_lock(
        path,
        owner={"operation": "append_production_evidence"},
        attempts=1,
        stale_after_seconds=300.0,
    )
    if not lock:
        raise ProductionEvidenceLedgerError(f"ledger writer lock is held: {path}")
    try:
        entries = _read_entries(path)
        verification = verify_chain(entries)
        if verification["status"] != "PASS":
            raise ProductionEvidenceLedgerError(
                f"existing ledger chain is invalid: {verification['errors'][0]}"
            )
        content = _record_content(dict(entry))
        if not content.get("entry_key"):
            raise ProductionEvidenceLedgerError("ledger entry_key is required")
        record_hash = canonical_payload_sha256(content)
        for existing in entries:
            if existing.get("entry_key") != content["entry_key"]:
                continue
            if existing.get("record_sha256") == record_hash:
                return {
                    "status": "PASS",
                    "appended": False,
                    "idempotent": True,
                    "entry": existing,
                    "verification": verification,
                }
            raise ProductionEvidenceLedgerError(
                f"conflicting immutable entry_key {content['entry_key']!r}"
            )
        row = {
            **content,
            "sequence": len(entries) + 1,
            "recorded_at_utc": _utc_now(now),
            "previous_entry_sha256": verification["entry_chain_sha256"],
            "record_sha256": record_hash,
        }
        row["entry_sha256"] = _entry_hash(row)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        post = verify_chain([*entries, row])
        if post["status"] != "PASS":
            raise ProductionEvidenceLedgerError(f"post-append chain verification failed: {post['errors']}")
        return {
            "status": "PASS",
            "appended": True,
            "idempotent": False,
            "entry": row,
            "verification": post,
        }
    finally:
        release_writer_lock(lock)


def build_clean_day_entry(
    fleet_path: str | Path = DEFAULT_FLEET,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    fleet_path = Path(fleet_path)
    fleet = _read_json(fleet_path)
    blockers: list[dict[str, Any]] = []
    target_text = _field(fleet, "clean_active_day_countability", "target_date")
    target = _parse_date(target_text)
    local_now = (now or datetime.now(timezone.utc)).astimezone(TORONTO)
    if target is None:
        _blocker(blockers, "target_date_invalid", "target_date", target_text, "ISO date")
    elif target >= local_now.date():
        _blocker(
            blockers,
            "target_day_not_closed",
            "target_date",
            target_text,
            f"before {local_now.date().isoformat()}",
        )
    if fleet.get("evidence_frozen") is not True:
        _blocker(
            blockers,
            "closed_day_evidence_not_frozen",
            "evidence_frozen",
            fleet.get("evidence_frozen"),
            "true",
        )
    generated_at = _parse_datetime(fleet.get("generated_at_utc"))
    if generated_at is None:
        _blocker(
            blockers,
            "evidence_timestamp_invalid",
            "generated_at_utc",
            fleet.get("generated_at_utc"),
            "timezone-aware timestamp",
        )

    release_id, manifest_hash = _release_identity(fleet)
    if not release_id:
        _blocker(blockers, "release_id_missing", "release_id", release_id, "non-empty")
    if not _valid_sha256(manifest_hash):
        _blocker(
            blockers,
            "release_manifest_hash_invalid",
            "release_manifest_sha256",
            manifest_hash,
            "64 lowercase hex characters",
        )
    if fleet.get("release_identity_status") != "verified":
        _blocker(
            blockers,
            "release_identity_not_verified",
            "release_identity_status",
            fleet.get("release_identity_status"),
            "verified",
        )

    _require_equal(blockers, fleet, ("summary", "market_count"), 12, "market_count_not_12")
    _require_equal(blockers, fleet, ("summary", "critical_alerts"), 0, "critical_alerts_present")
    _require_equal(blockers, fleet, ("live_forward_slo", "status"), "PASS", "live_forward_failed")
    _require_equal(
        blockers,
        fleet,
        ("live_forward_slo", "counts_toward_live_forward_gate"),
        True,
        "live_forward_not_countable",
    )
    _require_equal(
        blockers,
        fleet,
        ("clean_active_day_countability", "status"),
        "PASS",
        "clean_day_gate_failed",
    )
    _require_equal(
        blockers,
        fleet,
        ("clean_active_day_countability", "counts_toward_clean_active_day"),
        True,
        "clean_day_not_countable",
    )
    _require_equal(
        blockers,
        fleet,
        ("clean_active_day_countability", "operational_blocker_count"),
        0,
        "clean_day_blockers_present",
    )
    _require_equal(blockers, fleet, ("current_code_soak", "status"), "PASS", "soak_failed")
    _require_equal(
        blockers,
        fleet,
        ("current_code_soak", "counts_toward_active_day"),
        True,
        "soak_not_countable",
    )
    _require_equal(
        blockers,
        fleet,
        ("runtime_identity_evidence", "status"),
        "PASS",
        "runtime_identity_failed",
    )
    _require_equal(
        blockers,
        fleet,
        ("runtime_identity_evidence", "runtime_identity_count"),
        1,
        "runtime_identity_not_singular",
    )
    _require_equal(
        blockers,
        fleet,
        ("runtime_identity_evidence", "mixed_runtime_identity"),
        False,
        "runtime_identity_mixed",
    )
    _require_equal(
        blockers,
        fleet,
        ("runtime_identity_evidence", "reconciliation_applied"),
        False,
        "runtime_reconciliation_not_allowed",
    )
    _require_equal(
        blockers,
        fleet,
        ("collection", "snapshot_cadence_proof", "summary", "status"),
        "PASS",
        "snapshot_cadence_failed",
    )
    _require_equal(
        blockers,
        fleet,
        ("collection", "snapshot_cadence_proof", "summary", "total_gap_count"),
        0,
        "snapshot_gaps_present",
    )
    _require_equal(
        blockers,
        fleet,
        ("collection", "source_status_proof", "summary", "status"),
        "PASS",
        "source_status_failed",
    )
    _require_equal(
        blockers,
        fleet,
        ("collection", "early_hour_coverage_proof", "summary", "status"),
        "PASS",
        "early_hour_coverage_failed",
    )
    _require_equal(
        blockers,
        fleet,
        (
            "collection",
            "early_hour_coverage_proof",
            "summary",
            "counts_toward_early_hour_evidence",
        ),
        True,
        "early_hour_not_countable",
    )
    _require_number(
        blockers,
        fleet,
        ("live_forward_slo", "clob_book_age_p99_seconds"),
        lambda value: value < 120.0,
        "<120",
        "clob_p99_too_old",
    )
    _require_number(
        blockers,
        fleet,
        ("live_forward_slo", "near_close_clob_book_age_p99_seconds"),
        lambda value: value < 30.0,
        "<30",
        "near_close_clob_p99_too_old",
    )

    recordability_codes = {
        "target_date_invalid",
        "target_day_not_closed",
        "closed_day_evidence_not_frozen",
        "evidence_timestamp_invalid",
        "release_id_missing",
        "release_manifest_hash_invalid",
        "release_identity_not_verified",
    }
    return {
        "schema_version": CLEAN_DAY_SCHEMA_VERSION,
        "entry_type": "clean_active_day",
        "entry_key": f"clean_day:{target_text or 'unknown'}",
        "target_date": target_text,
        "status": "PASS" if not blockers else "BLOCK",
        "recordable": not any(row["code"] in recordability_codes for row in blockers),
        "release_id": release_id,
        "release_manifest_sha256": manifest_hash,
        "market_count": _field(fleet, "summary", "market_count"),
        "all_market_days_countable": not blockers,
        "singular_release_identity": bool(
            release_id
            and _valid_sha256(manifest_hash)
            and _field(fleet, "runtime_identity_evidence", "runtime_identity_count") == 1
            and _field(fleet, "runtime_identity_evidence", "mixed_runtime_identity") is False
        ),
        "capture_slos_pass": all(
            blocker["code"]
            not in {
                "live_forward_failed",
                "live_forward_not_countable",
                "snapshot_cadence_failed",
                "snapshot_gaps_present",
                "source_status_failed",
                "early_hour_coverage_failed",
                "early_hour_not_countable",
                "clob_p99_too_old",
                "near_close_clob_p99_too_old",
            }
            for blocker in blockers
        ),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "source_evidence": [_source_record(fleet_path, fleet)],
    }


def _manifest_sla_pass(payload: Mapping[str, Any]) -> bool:
    sla = payload.get("sla")
    sla = sla if isinstance(sla, Mapping) else {}
    duration = _number(sla.get("duration_seconds"))
    limit = _number(sla.get("limit_seconds"))
    return bool(
        sla.get("status") == "PASS"
        and sla.get("predeclared") is True
        and duration is not None
        and limit is not None
        and limit > 0
        and 0 <= duration <= limit
    )


def _manifest_sla_contract_complete(payload: Mapping[str, Any]) -> bool:
    sla = payload.get("sla")
    return bool(
        isinstance(sla, Mapping)
        and sla.get("status") in {"PASS", "BLOCK"}
        and isinstance(sla.get("predeclared"), bool)
        and "duration_seconds" in sla
        and "limit_seconds" in sla
    )


def _invocation_is_scheduled(payload: Mapping[str, Any]) -> bool:
    invocation = payload.get("invocation")
    invocation = invocation if isinstance(invocation, Mapping) else {}
    return bool(
        invocation.get("status") == "PASS"
        and invocation.get("mode") == "scheduled"
        and invocation.get("scheduler_attested") is True
        and bool(invocation.get("task_name"))
        and _valid_sha256(invocation.get("task_definition_sha256"))
        and _field(invocation, "contract", "status") == "PASS"
        and _valid_sha256(_field(invocation, "contract", "contract_sha256"))
        and _field(invocation, "task_run_correlation", "status") == "PASS"
    )


def _invocation_contract_complete(payload: Mapping[str, Any]) -> bool:
    invocation = payload.get("invocation")
    return bool(
        isinstance(invocation, Mapping)
        and invocation.get("status") in {"PASS", "BLOCK"}
        and invocation.get("mode") in {"scheduled", "manual_or_unverified"}
        and invocation.get("task_name")
        and isinstance(invocation.get("scheduler_attested"), bool)
        and isinstance(invocation.get("manual_intervention"), bool)
        and "resume_from_step" in invocation
        and isinstance(invocation.get("resumed"), bool)
        and isinstance(invocation.get("contract"), Mapping)
        and isinstance(invocation.get("task_run_correlation"), Mapping)
    )


def _lock_contract_complete(payload: Mapping[str, Any]) -> bool:
    lock_proof = payload.get("lock_proof")
    return bool(
        isinstance(lock_proof, Mapping)
        and lock_proof.get("status") in {"PASS", "BLOCK"}
        and isinstance(lock_proof.get("instrumented"), bool)
        and isinstance(lock_proof.get("stale_lock_count"), int)
        and isinstance(lock_proof.get("stale_lock_repair_count"), int)
        and isinstance(lock_proof.get("forced_lock_acquisition_count"), int)
        and isinstance(lock_proof.get("forced_lock_repair_count"), int)
    )


def _has_stale_or_forced_lock(payload: Mapping[str, Any]) -> bool:
    lock_proof = payload.get("lock_proof")
    lock_proof = lock_proof if isinstance(lock_proof, Mapping) else {}
    return not (
        lock_proof.get("status") == "PASS"
        and lock_proof.get("instrumented") is True
        and lock_proof.get("stale_lock_count") == 0
        and lock_proof.get("stale_lock_repair_count") == 0
        and lock_proof.get("forced_lock_acquisition_count") == 0
        and lock_proof.get("forced_lock_repair_count") == 0
    )


def _release_binding_contract_complete(payload: Mapping[str, Any]) -> bool:
    identity = payload.get("release_identity")
    identity = identity if isinstance(identity, Mapping) else {}
    release_id, manifest_hash = _release_identity(payload)
    return bool(
        identity.get("status") == "PASS"
        and identity.get("served_bindings_verified") is True
        and release_id
        and _valid_sha256(manifest_hash)
        and payload.get("release_identity_status") == "verified_serving_binding"
    )


def build_unattended_cycle_entry(
    stage_a_path: str | Path = DEFAULT_STAGE_A,
    stage_b_path: str | Path = DEFAULT_STAGE_B,
    nightly_path: str | Path = DEFAULT_NIGHTLY,
) -> dict[str, Any]:
    stage_a_path = Path(stage_a_path)
    stage_b_path = Path(stage_b_path)
    nightly_path = Path(nightly_path)
    stage_a = _read_json(stage_a_path)
    stage_b = _read_json(stage_b_path)
    nightly = _read_json(nightly_path)
    blockers: list[dict[str, Any]] = []
    target_dates = [
        stage_a.get("target_date"),
        stage_b.get("target_date"),
        _field(nightly, "settled_day_freshness", "target_date"),
    ]
    parsed_dates = [_parse_date(value) for value in target_dates]
    target_text = str(target_dates[0] or "")
    if any(value is None for value in parsed_dates) or len(set(target_dates)) != 1:
        _blocker(
            blockers,
            "mixed_target_dates",
            "target_dates",
            target_dates,
            "one identical ISO date",
        )

    identities = [_release_identity(payload) for payload in (stage_a, stage_b, nightly)]
    release_ids = {identity[0] for identity in identities if identity[0]}
    manifest_hashes = {identity[1] for identity in identities if identity[1]}
    release_id = next(iter(release_ids), "")
    manifest_hash = next(iter(manifest_hashes), "")
    if len(release_ids) != 1 or any(not identity[0] for identity in identities):
        _blocker(
            blockers,
            "release_id_mismatch_or_missing",
            "release_id",
            identities,
            "one explicit identical release ID",
        )
    if (
        len(manifest_hashes) != 1
        or any(not _valid_sha256(identity[1]) for identity in identities)
    ):
        _blocker(
            blockers,
            "release_manifest_mismatch_or_missing",
            "release_manifest_sha256",
            identities,
            "one explicit identical SHA-256",
        )
    release_bindings_complete = all(
        _release_binding_contract_complete(payload)
        for payload in (stage_a, stage_b, nightly)
    )
    if not release_bindings_complete:
        _blocker(
            blockers,
            "release_binding_proof_missing",
            "release_identity",
            [payload.get("release_identity") for payload in (stage_a, stage_b, nightly)],
            "exact PASS verified serving binding for all producer inputs",
        )

    for label, payload in (("stage_a", stage_a), ("stage_b", stage_b)):
        if payload.get("status") != "COMPLETED" or payload.get("payload_status") != "ok":
            _blocker(
                blockers,
                f"{label}_not_ok",
                f"{label}.status",
                [payload.get("status"), payload.get("payload_status")],
                "COMPLETED/ok",
            )
        step_statuses = {str(row.get("status") or "") for row in payload.get("steps") or []}
        if not step_statuses or not step_statuses.issubset({"ok", "skipped"}):
            _blocker(
                blockers,
                f"{label}_step_failure",
                f"{label}.steps",
                sorted(step_statuses),
                "only ok/skipped terminal statuses",
            )
        if not _manifest_sla_pass(payload):
            _blocker(blockers, f"{label}_outside_sla", f"{label}.sla", None, "PASS")

    nightly_status = str(nightly.get("status") or "")
    if nightly_status not in {"shadow", "promote_ready"}:
        _blocker(
            blockers,
            "nightly_not_ok",
            "nightly.status",
            nightly_status,
            "shadow or promote_ready",
        )
    nightly_step_statuses = {
        str(row.get("status") or "") for row in nightly.get("steps") or []
    }
    if not nightly_step_statuses or not nightly_step_statuses.issubset({"ok", "skipped"}):
        _blocker(
            blockers,
            "nightly_step_failure",
            "nightly.steps",
            sorted(nightly_step_statuses),
            "only ok/skipped terminal statuses",
        )
    if nightly.get("dry_run") is not False:
        _blocker(blockers, "nightly_dry_or_unknown", "nightly.dry_run", nightly.get("dry_run"), "false")
    if (
        _field(nightly, "nightly_sla", "state") != "OK"
        or _field(nightly, "nightly_sla", "fresh_for_latest_window") is not True
        or bool(_field(nightly, "nightly_sla", "alerts"))
    ):
        _blocker(
            blockers,
            "nightly_outside_sla",
            "nightly.nightly_sla",
            nightly.get("nightly_sla"),
            "state OK, fresh, zero alerts",
        )
    if not _manifest_sla_pass(nightly):
        _blocker(
            blockers,
            "nightly_stage_outside_sla",
            "nightly.sla",
            nightly.get("sla"),
            "predeclared exact PASS duration",
        )

    scheduled = all(_invocation_is_scheduled(payload) for payload in (stage_a, stage_b, nightly))
    invocation_complete = all(
        _invocation_contract_complete(payload) for payload in (stage_a, stage_b, nightly)
    )
    if not invocation_complete:
        _blocker(
            blockers,
            "invocation_provenance_missing",
            "invocation",
            [payload.get("invocation") for payload in (stage_a, stage_b, nightly)],
            "explicit mode/task/manual/resume fields",
        )
    if not scheduled:
        _blocker(
            blockers,
            "invocation_not_proven_scheduled",
            "invocation",
            [payload.get("invocation") for payload in (stage_a, stage_b, nightly)],
            "scheduled task provenance for all three inputs",
        )
    scheduler_attestation_failed = any(
        _field(payload, "invocation", "status") != "PASS"
        or _field(payload, "invocation", "scheduler_attested") is not True
        or _field(payload, "invocation", "contract", "status") != "PASS"
        or _field(payload, "invocation", "task_run_correlation", "status") != "PASS"
        for payload in (stage_a, stage_b, nightly)
    )
    if scheduler_attestation_failed:
        _blocker(
            blockers,
            "scheduler_attestation_failed",
            "invocation",
            [payload.get("invocation") for payload in (stage_a, stage_b, nightly)],
            "OS-attested enabled/running task with exact action and fresh start correlation",
        )
    lock_contract_complete = all(
        _lock_contract_complete(payload) for payload in (stage_a, stage_b, nightly)
    )
    if not lock_contract_complete:
        _blocker(
            blockers,
            "lock_proof_missing",
            "lock_proof",
            [payload.get("lock_proof") for payload in (stage_a, stage_b, nightly)],
            "explicit integer stale/forced counts",
        )
    stale_lock = any(_has_stale_or_forced_lock(payload) for payload in (stage_a, stage_b, nightly))
    if stale_lock:
        _blocker(
            blockers,
            "stale_or_forced_lock_repair",
            "lock_proof",
            [payload.get("lock_proof") for payload in (stage_a, stage_b, nightly)],
            "zero stale/forced repairs",
        )
    resume_or_manual = any(
        bool(_field(payload, "invocation", "resume_from_step"))
        or _field(payload, "invocation", "resumed") is not False
        or _field(payload, "invocation", "manual_intervention") is not False
        for payload in (stage_a, stage_b, nightly)
    )
    if resume_or_manual:
        _blocker(
            blockers,
            "manual_intervention_or_resume",
            "invocation.manual_intervention",
            True,
            "false and no resume",
        )

    consistency = _field(nightly, "daily_learning", "input_consistency_status")
    freshness = _field(nightly, "daily_learning", "input_freshness_status")
    inconsistent_input_count = 0 if consistency == "PASS" and freshness == "PASS" else 1
    if inconsistent_input_count:
        _blocker(
            blockers,
            "nightly_inputs_inconsistent_or_stale",
            "nightly.daily_learning",
            {"input_consistency_status": consistency, "input_freshness_status": freshness},
            "both PASS",
        )

    activation = nightly.get("candidate_release")
    activation = activation if isinstance(activation, Mapping) else {}
    pointer_changed = bool(activation.get("pointer_changed"))
    reviewed = activation.get("reviewed") is True and bool(activation.get("reviewed_by"))
    unreviewed_promotion = pointer_changed and not reviewed
    if unreviewed_promotion:
        _blocker(
            blockers,
            "unreviewed_promotion",
            "nightly.candidate_release",
            activation,
            "no pointer change or explicit reviewed proof",
        )

    nightly_sla = nightly.get("nightly_sla")
    nightly_sla_complete = bool(
        isinstance(nightly_sla, Mapping)
        and nightly_sla.get("state")
        and isinstance(nightly_sla.get("fresh_for_latest_window"), bool)
        and isinstance(nightly_sla.get("alerts"), list)
    )
    sla_contract_complete = (
        _manifest_sla_contract_complete(stage_a)
        and _manifest_sla_contract_complete(stage_b)
        and _manifest_sla_contract_complete(nightly)
        and nightly_sla_complete
    )
    if not sla_contract_complete:
        _blocker(
            blockers,
            "sla_proof_missing",
            "sla",
            [stage_a.get("sla"), stage_b.get("sla"), nightly.get("nightly_sla")],
            "explicit daily and nightly SLA proofs",
        )
    inside_sla = (
        _manifest_sla_pass(stage_a)
        and _manifest_sla_pass(stage_b)
        and _manifest_sla_pass(nightly)
        and _field(nightly, "nightly_sla", "state") == "OK"
    )
    daily_pass = not any(
        blocker["code"].startswith("stage_a_")
        or blocker["code"].startswith("stage_b_")
        for blocker in blockers
    )
    nightly_pass = not any(
        blocker["code"].startswith("nightly_") for blocker in blockers
    )
    completion_proof_complete = bool(
        _parse_datetime(stage_a.get("completed_at_utc"))
        and _parse_datetime(stage_b.get("completed_at_utc"))
        and _parse_datetime(
            nightly.get("finished_at_utc") or nightly.get("generated_at_utc")
        )
    )
    if not completion_proof_complete:
        _blocker(
            blockers,
            "completion_timestamp_missing",
            "completion_timestamps",
            [
                stage_a.get("completed_at_utc"),
                stage_b.get("completed_at_utc"),
                nightly.get("finished_at_utc") or nightly.get("generated_at_utc"),
            ],
            "three timezone-aware terminal timestamps",
        )
    recordability_codes = {
        "mixed_target_dates",
        "release_id_mismatch_or_missing",
        "release_manifest_mismatch_or_missing",
        "release_binding_proof_missing",
        "invocation_provenance_missing",
        "scheduler_attestation_failed",
        "lock_proof_missing",
        "sla_proof_missing",
        "completion_timestamp_missing",
    }
    return {
        "schema_version": UNATTENDED_SCHEMA_VERSION,
        "entry_type": "unattended_daily_nightly_cycle",
        "entry_key": f"unattended_cycle:{target_text or 'unknown'}",
        "target_date": target_text,
        "status": "PASS" if not blockers else "BLOCK",
        "recordable": not any(row["code"] in recordability_codes for row in blockers),
        "release_id": release_id,
        "release_manifest_sha256": manifest_hash,
        "daily_refresh_pass": daily_pass,
        "nightly_pass": nightly_pass,
        "inside_sla": inside_sla,
        "manual_repair": resume_or_manual or not scheduled,
        "stale_lock": stale_lock,
        "mixed_target_date": len(set(target_dates)) != 1,
        "unreviewed_promotion": unreviewed_promotion,
        "inconsistent_input_count": inconsistent_input_count,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "source_evidence": [
            _source_record(stage_a_path, stage_a),
            _source_record(stage_b_path, stage_b),
            _source_record(nightly_path, nightly),
        ],
    }


def _consecutive_suffix(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        entries,
        key=lambda row: (_parse_date(row.get("target_date")) or date.min, row.get("sequence", 0)),
    )
    streak: list[dict[str, Any]] = []
    for entry in reversed(ordered):
        target = _parse_date(entry.get("target_date"))
        if entry.get("status") != "PASS" or target is None:
            break
        if not streak:
            streak.append(entry)
            continue
        newer = _parse_date(streak[-1].get("target_date"))
        if (
            newer is None
            or target != newer - timedelta(days=1)
            or entry.get("release_id") != streak[-1].get("release_id")
            or entry.get("release_manifest_sha256")
            != streak[-1].get("release_manifest_sha256")
        ):
            break
        streak.append(entry)
    return list(reversed(streak))


def build_clean_day_summary(entries_or_path: Iterable[Mapping[str, Any]] | str | Path) -> dict[str, Any]:
    entries = (
        _read_entries(entries_or_path)
        if isinstance(entries_or_path, (str, Path))
        else [dict(row) for row in entries_or_path]
    )
    verification = verify_chain(entries)
    streak = _consecutive_suffix(entries) if verification["status"] == "PASS" else []
    latest = entries[-1] if entries else {}
    release_ids = {row.get("release_id") for row in streak if row.get("release_id")}
    manifest_hashes = {
        row.get("release_manifest_sha256")
        for row in streak
        if row.get("release_manifest_sha256")
    }
    summary = {
        "consecutive_clean_active_days": len(streak),
        "market_count": min((int(row.get("market_count") or 0) for row in streak), default=0),
        "all_market_days_countable": bool(streak)
        and all(row.get("all_market_days_countable") is True for row in streak),
        "singular_release_identity": bool(streak)
        and len(release_ids) == 1
        and len(manifest_hashes) == 1,
        "capture_slos_pass": bool(streak)
        and all(row.get("capture_slos_pass") is True for row in streak),
        "append_only": True,
        "ledger_integrity_status": verification["status"],
        "entry_count": len(entries),
        "entry_chain_sha256": verification["entry_chain_sha256"],
    }
    return {
        "schema_version": CLEAN_DAY_SCHEMA_VERSION,
        "generated_at_utc": _utc_now(),
        "status": "PASS" if verification["status"] == "PASS" and len(streak) >= 3 else "BLOCK",
        "evidence_contract": "append_only_clean_day_ledger",
        "release_id": latest.get("release_id") or "",
        "release_manifest_sha256": latest.get("release_manifest_sha256") or "",
        "summary": summary,
        "chain_errors": verification["errors"],
        "streak_target_dates": [row.get("target_date") for row in streak],
        "latest_entry": latest,
    }


def build_unattended_summary(entries_or_path: Iterable[Mapping[str, Any]] | str | Path) -> dict[str, Any]:
    entries = (
        _read_entries(entries_or_path)
        if isinstance(entries_or_path, (str, Path))
        else [dict(row) for row in entries_or_path]
    )
    verification = verify_chain(entries)
    streak = _consecutive_suffix(entries) if verification["status"] == "PASS" else []
    latest = entries[-1] if entries else {}
    exception_rows = streak if streak else ([latest] if latest else [])
    summary = {
        "consecutive_unattended_cycles": len(streak),
        "daily_refresh_pass_count": sum(row.get("daily_refresh_pass") is True for row in streak),
        "nightly_pass_count": sum(row.get("nightly_pass") is True for row in streak),
        "manual_repair_count": sum(row.get("manual_repair") is True for row in exception_rows),
        "stale_lock_count": sum(row.get("stale_lock") is True for row in exception_rows),
        "mixed_target_date_count": sum(
            row.get("mixed_target_date") is True for row in exception_rows
        ),
        "unreviewed_promotion_count": sum(
            row.get("unreviewed_promotion") is True for row in exception_rows
        ),
        "inconsistent_input_count": sum(
            int(row.get("inconsistent_input_count") or 0) for row in exception_rows
        ),
        "inside_sla_count": sum(row.get("inside_sla") is True for row in streak),
        "append_only": True,
        "ledger_integrity_status": verification["status"],
        "entry_count": len(entries),
        "entry_chain_sha256": verification["entry_chain_sha256"],
    }
    return {
        "schema_version": UNATTENDED_SCHEMA_VERSION,
        "generated_at_utc": _utc_now(),
        "status": "PASS" if verification["status"] == "PASS" and len(streak) >= 7 else "BLOCK",
        "evidence_contract": "append_only_unattended_cycle_ledger",
        "release_id": latest.get("release_id") or "",
        "release_manifest_sha256": latest.get("release_manifest_sha256") or "",
        "summary": summary,
        "chain_errors": verification["errors"],
        "streak_target_dates": [row.get("target_date") for row in streak],
        "latest_entry": latest,
    }


def render_summary_markdown(payload: Mapping[str, Any], title: str) -> str:
    summary = payload.get("summary") or {}
    lines = [
        f"# {title}",
        "",
        f"Status: **{payload.get('status')}**",
        "",
        f"Release: `{payload.get('release_id') or '-'}`",
        "",
        "| Field | Value |",
        "| --- | --- |",
    ]
    for key, value in summary.items():
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "## Current streak", ""])
    dates = payload.get("streak_target_dates") or []
    lines.append(", ".join(f"`{value}`" for value in dates) if dates else "No qualifying streak.")
    latest = payload.get("latest_entry") or {}
    blockers = latest.get("blockers") or []
    lines.extend(["", "## Latest blockers", ""])
    if blockers:
        for blocker in blockers:
            lines.append(
                f"- `{blocker.get('code')}`: {blocker.get('field')} was "
                f"`{blocker.get('actual')}`; expected {blocker.get('expected')}."
            )
    else:
        lines.append("No blocker in the latest entry.")
    lines.append("")
    return "\n".join(lines)


def _write_text_atomic(path: str | Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


def write_summary(path: str | Path, report_path: str | Path, payload: Mapping[str, Any], title: str) -> None:
    write_json_atomic(path, payload, trailing_newline=True)
    _write_text_atomic(report_path, render_summary_markdown(payload, title))


def _append_clean(args) -> dict[str, Any]:
    entry = build_clean_day_entry(args.fleet)
    if not entry.get("recordable") or entry.get("status") != "PASS":
        raise ProductionEvidenceLedgerError(
            "clean-day evidence is not exact PASS; refusing immutable append"
        )
    result = append_entry(args.ledger, entry)
    summary = build_clean_day_summary(args.ledger)
    write_summary(args.out, args.report, summary, "Production Clean-Day Ledger")
    return {"append": result, "summary": summary}


def _append_unattended(args) -> dict[str, Any]:
    entry = build_unattended_cycle_entry(args.stage_a, args.stage_b, args.nightly)
    if not entry.get("recordable") or entry.get("status") != "PASS":
        raise ProductionEvidenceLedgerError(
            "unattended-cycle producer proofs are not exact PASS; refusing immutable append"
        )
    result = append_entry(args.ledger, entry)
    summary = build_unattended_summary(args.ledger)
    write_summary(args.out, args.report, summary, "Unattended Daily/Nightly Cycle Ledger")
    return {"append": result, "summary": summary}


def _verify(args) -> dict[str, Any]:
    clean = build_clean_day_summary(args.clean_ledger)
    unattended = build_unattended_summary(args.unattended_ledger)
    write_summary(args.clean_out, args.clean_report, clean, "Production Clean-Day Ledger")
    write_summary(
        args.unattended_out,
        args.unattended_report,
        unattended,
        "Unattended Daily/Nightly Cycle Ledger",
    )
    return {"clean_day": clean, "unattended_cycle": unattended}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    clean = sub.add_parser("clean-day", help="Append one frozen closed-day fleet proof.")
    clean.add_argument("--fleet", default=str(DEFAULT_FLEET))
    clean.add_argument("--ledger", default=str(DEFAULT_CLEAN_DAY_JSONL))
    clean.add_argument("--out", default=str(DEFAULT_CLEAN_DAY_JSON))
    clean.add_argument("--report", default=str(DEFAULT_CLEAN_DAY_MD))
    clean.set_defaults(func=_append_clean)

    unattended = sub.add_parser(
        "unattended-cycle",
        help="Append one release-bound Stage A/Stage B/nightly cycle proof.",
    )
    unattended.add_argument("--stage-a", default=str(DEFAULT_STAGE_A))
    unattended.add_argument("--stage-b", default=str(DEFAULT_STAGE_B))
    unattended.add_argument("--nightly", default=str(DEFAULT_NIGHTLY))
    unattended.add_argument("--ledger", default=str(DEFAULT_UNATTENDED_JSONL))
    unattended.add_argument("--out", default=str(DEFAULT_UNATTENDED_JSON))
    unattended.add_argument("--report", default=str(DEFAULT_UNATTENDED_MD))
    unattended.set_defaults(func=_append_unattended)

    verify = sub.add_parser("verify", help="Verify both chains and atomically rebuild summaries.")
    verify.add_argument("--clean-ledger", default=str(DEFAULT_CLEAN_DAY_JSONL))
    verify.add_argument("--clean-out", default=str(DEFAULT_CLEAN_DAY_JSON))
    verify.add_argument("--clean-report", default=str(DEFAULT_CLEAN_DAY_MD))
    verify.add_argument("--unattended-ledger", default=str(DEFAULT_UNATTENDED_JSONL))
    verify.add_argument("--unattended-out", default=str(DEFAULT_UNATTENDED_JSON))
    verify.add_argument("--unattended-report", default=str(DEFAULT_UNATTENDED_MD))
    verify.set_defaults(func=_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = args.func(args)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
