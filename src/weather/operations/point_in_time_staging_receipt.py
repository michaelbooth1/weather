"""Receipt binding for staged production point-in-time source trios."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from weather.backtesting.settlement_ledger import (
    current_ledger_label,
    ledger_path_for_market,
    verify_ledger_history,
)
from weather.io import write_json_atomic
from weather.market.market_registry import REGISTRY
from weather.reporting.promotion.promotion_corpus import (
    PROMOTION_CORPUS_SCHEMA_VERSION,
    corpus_hash as promotion_corpus_hash,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("point_in_time_staging_receipt")
SOURCE_MANIFEST_SCHEMA_VERSION = schema_version(
    "production_point_in_time_preselection_source"
)
ARTIFACT_TYPE = "point_in_time_staging_receipt"
SOURCE_MANIFEST_ARTIFACT_TYPE = (
    "production_point_in_time_preselection_source_manifest"
)
TORONTO_MARKET_ID = "toronto"
DEFAULT_LOCK_DAYS = 14
MAX_SOURCE_MANIFEST_BYTES = 4 * 1024**2
MAX_REPLAY_MANIFEST_BYTES = 16 * 1024**2
MAX_MARKET_DAYS = 60
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TRIO_ROLES = (
    "preselection_source_corpus",
    "preselection_source_manifest",
    "source_replay_manifest",
)


class StagingReceiptError(ValueError):
    """The staged source cannot be authorized for the current Toronto lock."""


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _self_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        _canonical_json(
            {key: value for key, value in payload.items() if key != "receipt_sha256"}
        ).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: str | Path, *, chunk_bytes: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def _require_exact_lock_days(lock_days: Any) -> int:
    if isinstance(lock_days, bool) or not isinstance(lock_days, int):
        raise StagingReceiptError("lock_days must be exactly 14")
    if lock_days != DEFAULT_LOCK_DAYS:
        raise StagingReceiptError("staging receipts require exactly 14 lock days")
    return lock_days


def _read_bounded_json(
    path: Path,
    *,
    label: str,
    max_bytes: int,
) -> tuple[dict[str, Any], bytes]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError as exc:
        raise StagingReceiptError(f"{label} is unreadable: {path}") from exc
    if not raw:
        raise StagingReceiptError(f"{label} is empty")
    if len(raw) > max_bytes:
        raise StagingReceiptError(
            f"{label} exceeds the {max_bytes}-byte staging bound"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StagingReceiptError(f"{label} is not valid UTF-8") from exc

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in pairs:
            if key in payload:
                raise StagingReceiptError(
                    f"{label} contains duplicate JSON key {key!r}"
                )
            payload[key] = value
        return payload

    def reject_non_finite(value: str) -> None:
        raise StagingReceiptError(
            f"{label} contains non-finite JSON constant {value!r}"
        )

    try:
        payload = json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_finite,
        )
    except json.JSONDecodeError as exc:
        raise StagingReceiptError(f"{label} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise StagingReceiptError(f"{label} must be a JSON object")
    return payload, raw


def _positive_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise StagingReceiptError(f"{label} must be a positive integer")
    return value


def _manifest_inventory(
    payload: Mapping[str, Any],
    *,
    rows_field: str,
    label: str,
) -> dict[tuple[str, str], tuple[str, int, int, str]]:
    rows = payload.get(rows_field)
    if (
        not isinstance(rows, list)
        or not rows
        or len(rows) > MAX_MARKET_DAYS
    ):
        raise StagingReceiptError(
            f"{label} inventory must contain 1..{MAX_MARKET_DAYS} market-days"
        )
    inventory: dict[tuple[str, str], tuple[str, int, int, str]] = {}
    event_slugs: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise StagingReceiptError(
                f"{label} inventory row {index} must be an object"
            )
        event_slug = row.get("event_slug")
        target_date = row.get("target_date")
        market_id = row.get("market_id")
        label_hash = row.get("label_hash")
        if (
            not isinstance(event_slug, str)
            or not event_slug
            or event_slug != event_slug.strip()
            or not isinstance(target_date, str)
            or not isinstance(market_id, str)
            or not market_id
            or market_id != market_id.strip()
            or not isinstance(label_hash, str)
            or not SHA256_RE.fullmatch(label_hash)
        ):
            raise StagingReceiptError(
                f"{label} inventory row {index} has invalid identity fields"
            )
        try:
            parsed_date = date.fromisoformat(target_date)
        except ValueError as exc:
            raise StagingReceiptError(
                f"{label} inventory row {index} has an invalid target_date"
            ) from exc
        if parsed_date.isoformat() != target_date:
            raise StagingReceiptError(
                f"{label} inventory row {index} target_date is not canonical"
            )
        row_count = _positive_int(
            row.get("row_count"),
            label=f"{label} inventory row {index} row_count",
        )
        snapshot_count = _positive_int(
            row.get("snapshot_count"),
            label=f"{label} inventory row {index} snapshot_count",
        )
        if snapshot_count > row_count:
            raise StagingReceiptError(
                f"{label} inventory row {index} snapshot_count exceeds row_count"
            )
        coordinate = (target_date, market_id)
        if coordinate in inventory or event_slug in event_slugs:
            raise StagingReceiptError(
                f"{label} inventory contains a duplicate market-day"
            )
        inventory[coordinate] = (
            event_slug,
            row_count,
            snapshot_count,
            label_hash,
        )
        event_slugs.add(event_slug)
    return inventory


def _validated_lock_dates(lock: Mapping[str, Any]) -> list[str]:
    if (
        lock.get("market_id") != TORONTO_MARKET_ID
        or lock.get("ledger_relative_path")
        != f"{TORONTO_MARKET_ID}/ledger.jsonl"
        or lock.get("lock_days") != DEFAULT_LOCK_DAYS
    ):
        raise StagingReceiptError("staging receipt Toronto lock contract is invalid")
    target_dates = lock.get("target_dates")
    if (
        not isinstance(target_dates, list)
        or len(target_dates) != DEFAULT_LOCK_DAYS
        or any(not isinstance(value, str) for value in target_dates)
        or len(set(target_dates)) != len(target_dates)
        or target_dates != sorted(target_dates)
    ):
        raise StagingReceiptError(
            "staging receipt Toronto dates are missing, duplicated, or reordered"
        )
    try:
        parsed_dates = [date.fromisoformat(value) for value in target_dates]
    except ValueError as exc:
        raise StagingReceiptError(
            "staging receipt Toronto dates contain an invalid date"
        ) from exc
    if (
        any(parsed.isoformat() != value for parsed, value in zip(parsed_dates, target_dates))
        or any(
            current != previous + timedelta(days=1)
            for previous, current in zip(parsed_dates, parsed_dates[1:])
        )
    ):
        raise StagingReceiptError(
            "staging receipt Toronto dates are not a contiguous 14-day window"
        )
    revisions = lock.get("latest_revisions")
    if not isinstance(revisions, list) or len(revisions) != DEFAULT_LOCK_DAYS:
        raise StagingReceiptError(
            "staging receipt Toronto revision inventory is incomplete"
        )
    revision_dates = []
    for index, revision in enumerate(revisions):
        if not isinstance(revision, dict):
            raise StagingReceiptError(
                f"staging receipt Toronto revision {index} is malformed"
            )
        revision_date = revision.get("target_date")
        if (
            not isinstance(revision_date, str)
            or not isinstance(revision.get("event_slug"), str)
            or not revision.get("event_slug")
            or not isinstance(revision.get("revision_id"), str)
            or not revision.get("revision_id")
            or isinstance(revision.get("revision_number"), bool)
            or not isinstance(revision.get("revision_number"), int)
            or revision.get("revision_number") <= 0
            or not isinstance(revision.get("label_hash"), str)
            or not SHA256_RE.fullmatch(revision["label_hash"])
        ):
            raise StagingReceiptError(
                f"staging receipt Toronto revision {index} is malformed"
            )
        revision_dates.append(revision_date)
    if revision_dates != target_dates:
        raise StagingReceiptError(
            "staging receipt Toronto revisions do not match its target dates"
        )
    return list(target_dates)


def _validate_staged_manifest_pair(
    *,
    source_manifest: Mapping[str, Any],
    replay_manifest: Mapping[str, Any],
    replay_manifest_raw: bytes,
    corpus_sha256: str,
    corpus_bytes: int,
    lock: Mapping[str, Any],
) -> None:
    if (
        source_manifest.get("schema_version") != SOURCE_MANIFEST_SCHEMA_VERSION
        or source_manifest.get("artifact_type")
        != SOURCE_MANIFEST_ARTIFACT_TYPE
        or source_manifest.get("status") != "PASS"
        or source_manifest.get("candidate_dependent_fields_included") != []
    ):
        raise StagingReceiptError(
            "preselection source manifest contract is invalid"
        )
    recorded_manifest_hash = source_manifest.get("manifest_hash")
    unhashed_source = dict(source_manifest)
    unhashed_source.pop("manifest_hash", None)
    if (
        not isinstance(recorded_manifest_hash, str)
        or not SHA256_RE.fullmatch(recorded_manifest_hash)
        or recorded_manifest_hash
        != hashlib.sha256(
            _canonical_json(unhashed_source).encode("utf-8")
        ).hexdigest()
    ):
        raise StagingReceiptError(
            "preselection source manifest self-hash is invalid"
        )
    if replay_manifest.get("schema_version") != PROMOTION_CORPUS_SCHEMA_VERSION:
        raise StagingReceiptError("source replay manifest contract is invalid")
    replay_entries = replay_manifest.get("entries")
    source_inventory = _manifest_inventory(
        source_manifest,
        rows_field="inputs",
        label="preselection source manifest",
    )
    replay_inventory = _manifest_inventory(
        replay_manifest,
        rows_field="entries",
        label="source replay manifest",
    )
    if replay_manifest.get("corpus_hash") != promotion_corpus_hash(replay_entries):
        raise StagingReceiptError("source replay manifest corpus hash is invalid")
    replay_sha256 = hashlib.sha256(replay_manifest_raw).hexdigest()
    replay_binding = source_manifest.get("source_replay_manifest")
    if (
        not isinstance(replay_binding, dict)
        or replay_binding.get("sha256") != replay_sha256
        or replay_binding.get("corpus_hash") != replay_manifest.get("corpus_hash")
    ):
        raise StagingReceiptError(
            "preselection source manifest replay binding is invalid"
        )
    if source_inventory != replay_inventory:
        raise StagingReceiptError(
            "preselection source and replay manifest inventories differ"
        )
    derived_artifact = source_manifest.get("derived_artifact")
    counts = source_manifest.get("counts")
    derived_row_count = (
        derived_artifact.get("row_count")
        if isinstance(derived_artifact, dict)
        else None
    )
    accepted_rows = counts.get("accepted_rows") if isinstance(counts, dict) else None
    market_days_read = (
        counts.get("market_days_read") if isinstance(counts, dict) else None
    )
    inventory_row_count = sum(row[1] for row in source_inventory.values())
    if (
        not isinstance(derived_artifact, dict)
        or derived_artifact.get("sha256") != corpus_sha256
        or isinstance(derived_artifact.get("bytes"), bool)
        or not isinstance(derived_artifact.get("bytes"), int)
        or derived_artifact.get("bytes") != corpus_bytes
        or isinstance(derived_row_count, bool)
        or not isinstance(derived_row_count, int)
        or derived_row_count <= 0
        or isinstance(accepted_rows, bool)
        or not isinstance(accepted_rows, int)
        or accepted_rows != derived_row_count
        or derived_row_count != inventory_row_count
        or isinstance(market_days_read, bool)
        or not isinstance(market_days_read, int)
        or market_days_read != len(source_inventory)
    ):
        raise StagingReceiptError(
            "preselection source corpus binding or inventory counts are invalid"
        )
    if (
        replay_manifest.get("admit_promotion_countable") is not False
        or replay_manifest.get("include_reconstructed") is not False
        or replay_manifest.get("allow_unsettled") is not False
    ):
        raise StagingReceiptError(
            "source replay manifest admission semantics are not production-safe"
        )
    for index, entry in enumerate(replay_entries):
        market_id = entry["market_id"]
        spec = REGISTRY.get(market_id)
        if (
            spec is None
            or spec.display_unit != "F"
            or entry.get("settlement_unit") != "F"
            or entry.get("admitted_by") != "quality_grade"
            or entry.get("quality_grade") not in {"complete", "manual_override"}
        ):
            raise StagingReceiptError(
                "source replay manifest is not a grade-only registered "
                f"F-family corpus at entry {index}"
            )

    lock_dates = _validated_lock_dates(lock)
    fleet_dates = sorted({coordinate[0] for coordinate in source_inventory})
    if (
        len(fleet_dates) < DEFAULT_LOCK_DAYS
        or fleet_dates[-DEFAULT_LOCK_DAYS:] != lock_dates
    ):
        raise StagingReceiptError(
            "staged source latest 14 fleet dates do not match the Toronto lock dates"
        )


def _read_ledger_strict(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise StagingReceiptError(f"Toronto settlement ledger is missing: {path}")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            text = raw.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise StagingReceiptError(
                    f"Toronto settlement ledger line {line_number} is invalid JSON"
                ) from exc
            if not isinstance(row, dict):
                raise StagingReceiptError(
                    f"Toronto settlement ledger line {line_number} is not an object"
                )
            rows.append(row)
    if not rows:
        raise StagingReceiptError("Toronto settlement ledger is empty")
    return rows


def latest_toronto_lock_revisions(
    ledger_root: str | Path,
    *,
    lock_days: int = DEFAULT_LOCK_DAYS,
) -> dict[str, Any]:
    """Return the exact current trailing complete-grade Toronto lock."""

    if isinstance(lock_days, bool) or int(lock_days) <= 0:
        raise StagingReceiptError("lock_days must be a positive integer")
    lock_days = int(lock_days)
    ledger_root = Path(ledger_root).resolve()
    ledger_path = ledger_path_for_market(TORONTO_MARKET_ID, ledger_root).resolve()
    rows = _read_ledger_strict(ledger_path)
    verification = verify_ledger_history(rows)
    if verification.get("status") != "PASS":
        codes = ",".join(
            str(row.get("code") or "unknown")
            for row in verification.get("blockers") or ()
        )
        raise StagingReceiptError(
            f"Toronto settlement ledger integrity failure: {codes or 'unknown'}"
        )

    slugs = sorted(
        {
            str(row.get("event_slug") or "")
            for row in rows
            if row.get("market_id") == TORONTO_MARKET_ID
            and str(row.get("event_slug") or "")
        }
    )
    current_by_date: dict[str, dict[str, Any]] = {}
    for slug in slugs:
        selected = current_ledger_label(rows, slug)
        if not selected:
            continue
        target_date = str(selected.get("target_date") or "")
        try:
            date.fromisoformat(target_date)
        except ValueError as exc:
            raise StagingReceiptError(
                f"Toronto ledger row has an invalid target date: {target_date!r}"
            ) from exc
        if target_date in current_by_date:
            raise StagingReceiptError(
                f"Toronto ledger has multiple current rows for {target_date}"
            )
        current_by_date[target_date] = selected
    if not current_by_date:
        raise StagingReceiptError("Toronto settlement ledger has no current rows")

    latest_date = date.fromisoformat(max(current_by_date))
    target_dates = [
        (latest_date - timedelta(days=offset)).isoformat()
        for offset in range(lock_days - 1, -1, -1)
    ]
    revisions = []
    for target_date in target_dates:
        row = current_by_date.get(target_date)
        if row is None:
            raise StagingReceiptError(
                "latest Toronto lock is not contiguous: "
                f"missing current ledger row for {target_date}"
            )
        if row.get("quality_grade") != "complete":
            raise StagingReceiptError(
                "latest Toronto lock is not complete-grade: "
                f"{target_date} has quality {row.get('quality_grade')!r}"
            )
        revision_id = str(row.get("revision_id") or "")
        label_hash = str(row.get("label_hash") or "")
        if not revision_id or not label_hash:
            raise StagingReceiptError(
                f"Toronto ledger row for {target_date} lacks revision identity"
            )
        revisions.append(
            {
                "target_date": target_date,
                "event_slug": str(row.get("event_slug") or ""),
                "revision_id": revision_id,
                "revision_number": int(row.get("revision_number") or 0),
                "label_hash": label_hash,
            }
        )
    return {
        "market_id": TORONTO_MARKET_ID,
        "ledger_relative_path": f"{TORONTO_MARKET_ID}/ledger.jsonl",
        "lock_days": lock_days,
        "target_dates": target_dates,
        "latest_revisions": revisions,
    }


def _portable_relative_path(path: Path, root: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise StagingReceiptError(
            f"staged source file must be inside the receipt directory: {path}"
        ) from exc
    value = relative.as_posix()
    if not value or value == ".":
        raise StagingReceiptError("staged source relative path is empty")
    return value


def build_staging_receipt(
    *,
    receipt_path: str | Path,
    corpus_path: str | Path,
    manifest_path: str | Path,
    replay_manifest_path: str | Path,
    ledger_root: str | Path,
    lock_days: int = DEFAULT_LOCK_DAYS,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build, but do not persist, a receipt for one staged source trio."""

    lock_days = _require_exact_lock_days(lock_days)
    receipt_path = Path(receipt_path).resolve()
    source_paths = (
        Path(corpus_path).resolve(),
        Path(manifest_path).resolve(),
        Path(replay_manifest_path).resolve(),
    )
    for path in source_paths:
        if not path.is_file():
            raise StagingReceiptError(f"staged source file is missing: {path}")
    generated = generated_at_utc or datetime.now(timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(str(generated).replace("Z", "+00:00"))
    except ValueError as exc:
        raise StagingReceiptError("generated_at_utc is invalid") from exc
    if parsed.tzinfo is None:
        raise StagingReceiptError("generated_at_utc must be timezone-aware")

    current_lock = latest_toronto_lock_revisions(
        ledger_root,
        lock_days=lock_days,
    )
    source_manifest, source_manifest_raw = _read_bounded_json(
        source_paths[1],
        label="preselection source manifest",
        max_bytes=MAX_SOURCE_MANIFEST_BYTES,
    )
    replay_manifest, replay_manifest_raw = _read_bounded_json(
        source_paths[2],
        label="source replay manifest",
        max_bytes=MAX_REPLAY_MANIFEST_BYTES,
    )
    corpus_identity = (
        _sha256_file(source_paths[0]),
        source_paths[0].stat().st_size,
    )
    _validate_staged_manifest_pair(
        source_manifest=source_manifest,
        replay_manifest=replay_manifest,
        replay_manifest_raw=replay_manifest_raw,
        corpus_sha256=corpus_identity[0],
        corpus_bytes=corpus_identity[1],
        lock=current_lock,
    )

    root = receipt_path.parent
    identities = (
        corpus_identity,
        (
            hashlib.sha256(source_manifest_raw).hexdigest(),
            len(source_manifest_raw),
        ),
        (
            hashlib.sha256(replay_manifest_raw).hexdigest(),
            len(replay_manifest_raw),
        ),
    )
    trio = []
    for role, path, (sha256, byte_count) in zip(
        TRIO_ROLES,
        source_paths,
        identities,
    ):
        trio.append(
            {
                "role": role,
                "relative_path": _portable_relative_path(path, root),
                "sha256": sha256,
                "bytes": byte_count,
            }
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "generated_at_utc": parsed.astimezone(timezone.utc).isoformat(),
        "staged_source_trio": trio,
        "toronto_lock": current_lock,
    }
    payload["receipt_sha256"] = _self_hash(payload)
    return payload


def write_staging_receipt(**kwargs: Any) -> Path:
    receipt_path = Path(kwargs["receipt_path"]).resolve()
    payload = build_staging_receipt(**kwargs)
    return write_json_atomic(receipt_path, payload, trailing_newline=True)


def _load_receipt(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StagingReceiptError(f"staging receipt is missing: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise StagingReceiptError(f"staging receipt is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise StagingReceiptError("staging receipt must be a JSON object")
    return payload


def _validated_relative_path(value: Any) -> PurePosixPath:
    text = str(value or "")
    relative = PurePosixPath(text)
    if (
        not text
        or "\\" in text
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise StagingReceiptError(
            f"staging receipt path is not a portable relative name: {text!r}"
        )
    return relative


def verify_staging_receipt(
    *,
    receipt_path: str | Path,
    corpus_path: str | Path,
    manifest_path: str | Path,
    replay_manifest_path: str | Path,
    ledger_root: str | Path,
    lock_days: int = DEFAULT_LOCK_DAYS,
    expected_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify the trio and the exact latest Toronto ledger revisions."""

    lock_days = _require_exact_lock_days(lock_days)
    receipt_path = Path(receipt_path).resolve()
    payload = _load_receipt(receipt_path)
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("artifact_type") != ARTIFACT_TYPE
    ):
        raise StagingReceiptError("staging receipt schema or artifact type is invalid")
    if payload.get("receipt_sha256") != _self_hash(payload):
        raise StagingReceiptError("staging receipt self-hash mismatch")
    expected_receipt_sha256 = str(expected_receipt_sha256 or "").strip()
    if (
        expected_receipt_sha256
        and payload.get("receipt_sha256") != expected_receipt_sha256
    ):
        raise StagingReceiptError(
            "staging receipt identity differs from the verified preflight receipt"
        )

    expected_paths = (
        Path(corpus_path).resolve(),
        Path(manifest_path).resolve(),
        Path(replay_manifest_path).resolve(),
    )
    trio = payload.get("staged_source_trio")
    if (
        not isinstance(trio, list)
        or len(trio) != len(TRIO_ROLES)
        or any(not isinstance(row, dict) for row in trio)
        or [row.get("role") for row in trio] != list(TRIO_ROLES)
    ):
        raise StagingReceiptError("staging receipt does not bind the exact trio roles")
    for row, expected_path in zip(trio, expected_paths):
        relative = _validated_relative_path(row.get("relative_path"))
        bound_path = receipt_path.parent.joinpath(*relative.parts).resolve()
        if bound_path != expected_path:
            raise StagingReceiptError(
                f"staging receipt path mismatch for {row.get('role')}"
            )
        if not expected_path.is_file():
            raise StagingReceiptError(f"staged source file is missing: {expected_path}")

    source_manifest, source_manifest_raw = _read_bounded_json(
        expected_paths[1],
        label="preselection source manifest",
        max_bytes=MAX_SOURCE_MANIFEST_BYTES,
    )
    replay_manifest, replay_manifest_raw = _read_bounded_json(
        expected_paths[2],
        label="source replay manifest",
        max_bytes=MAX_REPLAY_MANIFEST_BYTES,
    )
    identities = (
        (_sha256_file(expected_paths[0]), expected_paths[0].stat().st_size),
        (
            hashlib.sha256(source_manifest_raw).hexdigest(),
            len(source_manifest_raw),
        ),
        (
            hashlib.sha256(replay_manifest_raw).hexdigest(),
            len(replay_manifest_raw),
        ),
    )
    for row, (sha256, byte_count) in zip(trio, identities):
        recorded_bytes = row.get("bytes")
        if (
            not isinstance(row.get("sha256"), str)
            or row.get("sha256") != sha256
            or isinstance(recorded_bytes, bool)
            or not isinstance(recorded_bytes, int)
            or recorded_bytes != byte_count
        ):
            raise StagingReceiptError(
                f"staged source identity mismatch for {row.get('role')}"
            )

    recorded_lock = payload.get("toronto_lock")
    if not isinstance(recorded_lock, dict):
        raise StagingReceiptError("staging receipt Toronto lock is missing")
    recorded_dates = _validated_lock_dates(recorded_lock)
    _validate_staged_manifest_pair(
        source_manifest=source_manifest,
        replay_manifest=replay_manifest,
        replay_manifest_raw=replay_manifest_raw,
        corpus_sha256=identities[0][0],
        corpus_bytes=identities[0][1],
        lock=recorded_lock,
    )
    current_lock = latest_toronto_lock_revisions(
        ledger_root,
        lock_days=lock_days,
    )
    if recorded_lock != current_lock:
        raise StagingReceiptError(
            "staging receipt does not match the latest Toronto lock revisions"
        )
    return {
        "status": "PASS",
        "receipt_path": str(receipt_path),
        "receipt_sha256": payload["receipt_sha256"],
        "target_dates": list(recorded_dates),
        "latest_revisions": list(current_lock["latest_revisions"]),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or verify a staged production PIT source receipt."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(command: argparse.ArgumentParser) -> None:
        command.add_argument("--receipt", required=True)
        command.add_argument("--corpus", required=True)
        command.add_argument("--manifest", required=True)
        command.add_argument("--replay-manifest", required=True)
        command.add_argument("--ledger-root", required=True)
        command.add_argument("--lock-days", type=int, default=DEFAULT_LOCK_DAYS)

    create = subparsers.add_parser("create")
    add_common(create)
    verify = subparsers.add_parser("verify")
    add_common(verify)
    verify.add_argument("--expected-receipt-sha256", default="")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    kwargs = {
        "receipt_path": args.receipt,
        "corpus_path": args.corpus,
        "manifest_path": args.manifest,
        "replay_manifest_path": args.replay_manifest,
        "ledger_root": args.ledger_root,
        "lock_days": args.lock_days,
    }
    try:
        if args.command == "create":
            path = write_staging_receipt(**kwargs)
            print(f"staging receipt written: {path}")
        else:
            result = verify_staging_receipt(
                **kwargs,
                expected_receipt_sha256=args.expected_receipt_sha256 or None,
            )
            print(
                "staging receipt verified: "
                f"{result['receipt_sha256']} dates={len(result['target_dates'])}"
            )
    except (OSError, StagingReceiptError, TypeError, ValueError) as exc:
        print(f"staging receipt BLOCK: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
