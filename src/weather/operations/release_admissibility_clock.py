"""Streaming release-admissibility receipts and their cheap streak collapse."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import stat
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from weather.backtesting.settlement_io import (
    band_value_hi,
    canonical_winning_band,
    ledger_label_matches_folder,
    resolve_outcome,
)
from weather.backtesting.settlement_ledger import (
    current_ledger_label,
    ledger_path_for_market,
    verify_ledger_history,
)
from weather.captured_input_hash import captured_input_payload_sha256
from weather.io import write_json_atomic
from weather.market.market_config import event_slug_for_date
from weather.market.market_registry import REGISTRY
from weather.release_artifacts import (
    ReleaseArtifactVerificationError,
    canonical_payload_sha256,
    strict_json_loads,
)
from weather.reporting.data_quality.feature_quality_quarantine import (
    apply_recovery_classification,
    dedupe_rows,
    feature_rows_for_folder,
    folder_context,
    replay_feature_contaminated,
    sidecar_rows_for_folder,
)
from weather.schema_registry import schema_version


RECEIPT_SCHEMA_VERSION = schema_version("release_admissibility_receipt")
CLOCK_SCHEMA_VERSION = schema_version("release_admissibility_clock")
RECEIPT_ARTIFACT_TYPE = "release_admissibility_receipt"
CLOCK_ARTIFACT_TYPE = "release_admissibility_clock"
DEFAULT_MARKET_ID = "toronto"
MAX_LEDGER_BYTES = 64 * 1024**2
MAX_SNAPSHOT_BYTES = 128 * 1024**2
MAX_REPLAY_BYTES = 64 * 1024**2
MAX_FEATURE_BYTES = 128 * 1024**2
MAX_SMALL_JSON_BYTES = 1024**2
MAX_ROWS = 250_000
MAX_LINE_BYTES = 8 * 1024**2
MAX_CSV_FIELD_BYTES = 1024**2
MASS_TOLERANCE = 1e-6


class AdmissibilityBlock(ValueError):
    """A stable release-admissibility blocker."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _self_hash(payload: Mapping[str, Any], field: str) -> str:
    return canonical_payload_sha256(payload, omit=(field,))


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _regular_bounded(path: Path, *, label: str, max_bytes: int) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise AdmissibilityBlock(f"{label}_missing", f"{label} is missing: {path}") from exc
    except OSError as exc:
        raise AdmissibilityBlock(f"{label}_unreadable", f"{label} is unreadable: {path}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise AdmissibilityBlock(f"{label}_not_regular", f"{label} must be a regular non-symlink file: {path}")
    if info.st_size <= 0:
        raise AdmissibilityBlock(f"{label}_empty", f"{label} is empty: {path}")
    if info.st_size > max_bytes:
        raise AdmissibilityBlock(
            f"{label}_oversized",
            f"{label} exceeds its {max_bytes}-byte production bound: {path}",
        )
    return info


def _sha256_stream(path: Path, *, label: str, max_bytes: int) -> tuple[str, int]:
    before = _regular_bounded(path, label=label, max_bytes=max_bytes)
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise AdmissibilityBlock(
                        f"{label}_oversized",
                        f"{label} changed beyond its production bound while being read: {path}",
                    )
                digest.update(chunk)
    except OSError as exc:
        raise AdmissibilityBlock(f"{label}_unreadable", f"{label} cannot be read: {path}") from exc
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or total != before.st_size:
        raise AdmissibilityBlock(f"{label}_changed", f"{label} changed while being verified: {path}")
    return digest.hexdigest(), total


def _input(path: Path, *, role: str, max_bytes: int) -> dict[str, Any]:
    digest, size = _sha256_stream(path, label=role, max_bytes=max_bytes)
    return {"role": role, "path": path.name, "bytes": size, "sha256": digest}


def _read_small_json(
    path: Path,
    *,
    role: str,
    item: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    item = item or _input(path, role=role, max_bytes=MAX_SMALL_JSON_BYTES)
    try:
        text = path.read_text(encoding="utf-8")
        payload = strict_json_loads(text, label=f"{role} {path}")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise AdmissibilityBlock(f"{role}_invalid", f"{role} is not strict UTF-8 JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AdmissibilityBlock(f"{role}_invalid", f"{role} must contain one JSON object: {path}")
    return payload, item


def _iter_csv(path: Path, *, role: str, max_bytes: int) -> Iterable[tuple[int, dict[str, str]]]:
    _regular_bounded(path, label=role, max_bytes=max_bytes)
    previous_limit = csv.field_size_limit()
    csv.field_size_limit(MAX_CSV_FIELD_BYTES)
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if not reader.fieldnames or any(not str(name or "").strip() for name in reader.fieldnames):
                raise AdmissibilityBlock(f"{role}_invalid_header", f"{role} has an invalid header: {path}")
            if len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise AdmissibilityBlock(f"{role}_duplicate_column", f"{role} has duplicate columns: {path}")
            for row_number, row in enumerate(reader, start=2):
                if row_number > MAX_ROWS + 1:
                    raise AdmissibilityBlock(f"{role}_row_bound", f"{role} exceeds {MAX_ROWS} rows: {path}")
                if None in row:
                    raise AdmissibilityBlock(f"{role}_malformed_row", f"{role} has extra fields at row {row_number}: {path}")
                yield row_number, dict(row)
    except AdmissibilityBlock:
        raise
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise AdmissibilityBlock(f"{role}_invalid", f"{role} cannot be parsed strictly: {path}: {exc}") from exc
    finally:
        csv.field_size_limit(previous_limit)


def _read_ledger(
    ledger_path: Path,
    *,
    event_slug: str,
    market_id: str,
    item: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    item = item or _input(
        ledger_path,
        role="settlement_ledger",
        max_bytes=MAX_LEDGER_BYTES,
    )
    rows: list[dict[str, Any]] = []
    try:
        with ledger_path.open("rb") as handle:
            for line_number, raw in enumerate(handle, start=1):
                if line_number > MAX_ROWS:
                    raise AdmissibilityBlock("ledger_row_bound", f"settlement ledger exceeds {MAX_ROWS} rows")
                if len(raw) > MAX_LINE_BYTES:
                    raise AdmissibilityBlock("ledger_line_bound", f"settlement ledger line {line_number} exceeds {MAX_LINE_BYTES} bytes")
                if not raw.strip():
                    continue
                try:
                    row = strict_json_loads(raw.decode("utf-8"), label=f"settlement ledger line {line_number}")
                except (UnicodeDecodeError, ValueError) as exc:
                    raise AdmissibilityBlock("ledger_invalid_jsonl", f"settlement ledger line {line_number} is invalid: {exc}") from exc
                if not isinstance(row, dict):
                    raise AdmissibilityBlock("ledger_invalid_jsonl", f"settlement ledger line {line_number} is not an object")
                rows.append(row)
    except AdmissibilityBlock:
        raise
    except OSError as exc:
        raise AdmissibilityBlock("ledger_unreadable", f"settlement ledger cannot be read: {ledger_path}") from exc
    verification = verify_ledger_history(rows)
    if verification.get("status") != "PASS":
        codes = ",".join(str(row.get("code") or "unknown") for row in verification.get("blockers") or ())
        raise AdmissibilityBlock("ledger_history_invalid", f"settlement ledger history verification failed: {codes}")
    label = current_ledger_label(rows, event_slug)
    if label is None:
        raise AdmissibilityBlock("ledger_label_missing", f"no settlement ledger revision exists for {event_slug}")
    if label.get("market_id") != market_id:
        raise AdmissibilityBlock("ledger_market_mismatch", f"latest ledger revision is not for {market_id}")
    if label.get("quality_grade") != "complete":
        raise AdmissibilityBlock(
            "ledger_not_complete",
            f"latest ledger revision quality_grade is {label.get('quality_grade')!r}, not 'complete'",
        )
    return label, verification, item


def _validate_distribution(record: Mapping[str, Any], *, snapshot_id: str) -> None:
    raw = record.get("recorded_distribution")
    if not isinstance(raw, Mapping) or not raw:
        raise AdmissibilityBlock("replay_distribution_missing", f"snapshot {snapshot_id} has no recorded_distribution")
    buckets: set[int] = set()
    total = 0.0
    for raw_bucket, raw_probability in raw.items():
        try:
            numeric_bucket = float(raw_bucket)
            bucket = int(numeric_bucket)
            probability = float(raw_probability)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AdmissibilityBlock("replay_distribution_invalid", f"snapshot {snapshot_id} has a non-numeric distribution value") from exc
        if (
            not math.isfinite(numeric_bucket)
            or numeric_bucket != bucket
            or bucket in buckets
            or not math.isfinite(probability)
            or probability < 0.0
            or probability > 1.0
        ):
            raise AdmissibilityBlock("replay_distribution_invalid", f"snapshot {snapshot_id} has a non-canonical finite distribution")
        buckets.add(bucket)
        total += probability
    if abs(total - 1.0) > MASS_TOLERANCE:
        raise AdmissibilityBlock("replay_probability_mass", f"snapshot {snapshot_id} distribution mass is {total:.12g}")


def _scan_snapshot_tape(
    path: Path,
    *,
    target_date: str,
    event_slug: str,
    label: Mapping[str, Any],
    item: dict[str, Any] | None = None,
) -> tuple[dict[str, dict[str, str]], int, int, dict[str, Any]]:
    item = item or _input(
        path,
        role="snapshot_tape",
        max_bytes=MAX_SNAPSHOT_BYTES,
    )
    required = {"snapshot_id", "captured_at_local", "range_label", "bin_kind", "bin_value_c"}
    contexts: dict[str, dict[str, str]] = {}
    coordinates: set[tuple[str, str, str, str]] = set()
    winners: defaultdict[str, int] = defaultdict(int)
    row_count = 0
    band_labels: set[str] = set()
    settlement_bucket = label.get("settlement_bucket")
    expected_winner = canonical_winning_band(label.get("winning_band"))
    for row_number, row in _iter_csv(path, role="snapshot_tape", max_bytes=MAX_SNAPSHOT_BYTES):
        if row_count == 0 and not required.issubset(row):
            raise AdmissibilityBlock("snapshot_columns_missing", f"snapshot tape is missing columns: {sorted(required - set(row))}")
        row_count += 1
        snapshot_id = str(row.get("snapshot_id") or "").strip()
        if not snapshot_id:
            raise AdmissibilityBlock("snapshot_identity_missing", f"snapshot tape row {row_number} has no snapshot_id")
        if row.get("event_slug") not in (None, "", event_slug):
            raise AdmissibilityBlock("snapshot_event_mismatch", f"snapshot {snapshot_id} has a conflicting event_slug")
        if row.get("target_date") not in (None, "", target_date):
            raise AdmissibilityBlock("snapshot_date_mismatch", f"snapshot {snapshot_id} has a conflicting target_date")
        if not str(row.get("captured_at_local") or "").startswith(target_date):
            raise AdmissibilityBlock("snapshot_local_date_mismatch", f"snapshot {snapshot_id} was not captured on local date {target_date}")
        identity = {
            key: str(row.get(key) or "")
            for key in ("captured_at_utc", "captured_at_local", "event_slug", "target_date", "market_id")
        }
        previous = contexts.setdefault(snapshot_id, identity)
        if previous != identity:
            raise AdmissibilityBlock("snapshot_identity_conflict", f"snapshot {snapshot_id} has conflicting identity fields")
        coordinate = (
            snapshot_id,
            str(row.get("range_label") or ""),
            str(row.get("bin_kind") or ""),
            str(row.get("bin_value_c") or ""),
        )
        if coordinate in coordinates:
            raise AdmissibilityBlock("snapshot_coordinate_duplicate", f"snapshot {snapshot_id} has a duplicate band coordinate")
        coordinates.add(coordinate)
        label_text = canonical_winning_band(row.get("range_label"))
        band_labels.add(label_text)
        try:
            value = int(float(str(row.get("bin_value_c") or "")))
            value_hi = band_value_hi(row.get("range_label"), value, row.get("bin_value_hi_c") or row.get("bin_value_hi"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise AdmissibilityBlock("snapshot_band_invalid", f"snapshot {snapshot_id} has an invalid band") from exc
        outcome = resolve_outcome(str(row.get("bin_kind") or ""), value, settlement_bucket, value_hi=value_hi)
        if outcome == 1:
            if label_text != expected_winner:
                raise AdmissibilityBlock("snapshot_winner_mismatch", f"snapshot {snapshot_id} winner {label_text!r} differs from ledger {expected_winner!r}")
            winners[snapshot_id] += 1
    if not contexts:
        raise AdmissibilityBlock("snapshot_tape_empty", "snapshot tape has no data rows")
    invalid_winners = [snapshot_id for snapshot_id in contexts if winners[snapshot_id] != 1]
    if invalid_winners:
        raise AdmissibilityBlock("snapshot_winner_count", f"{len(invalid_winners)} snapshots do not have exactly one ledger winner")
    for field, actual in (("row_count", row_count), ("snapshot_count", len(contexts)), ("band_count", len(band_labels))):
        recorded = label.get(field)
        if isinstance(recorded, int) and recorded != actual:
            raise AdmissibilityBlock(f"snapshot_{field}_mismatch", f"ledger {field}={recorded} but tape {field}={actual}")
    if not ledger_label_matches_folder(label, path.parent, snapshot_tape_sha256=item["sha256"]):
        raise AdmissibilityBlock("snapshot_ledger_hash_mismatch", "snapshot tape does not match the immutable ledger binding")
    return contexts, row_count, len(band_labels), item


def _scan_features(
    folder: Path,
    *,
    unit: str,
    snapshot_contexts: Mapping[str, Mapping[str, str]],
    item: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]], int, dict[str, Any] | None]:
    path = folder / "features_long.csv"
    if not path.exists():
        return [], {}, 0, None
    item = item or _input(
        path,
        role="feature_tape",
        max_bytes=MAX_FEATURE_BYTES,
    )
    context = folder_context(folder, unit=unit)
    feature_support: dict[str, dict[str, str]] = {}
    quarantines: list[dict[str, Any]] = []
    count = 0
    for _row_number, row in _iter_csv(path, role="feature_tape", max_bytes=MAX_FEATURE_BYTES):
        count += 1
        snapshot_id = str(row.get("snapshot_id") or "")
        if snapshot_id and snapshot_id not in snapshot_contexts:
            raise AdmissibilityBlock("feature_snapshot_unknown", f"feature tape references unknown snapshot {snapshot_id}")
        if snapshot_id:
            feature_support[snapshot_id] = row
        quarantines.extend(feature_rows_for_folder(folder, context, [row]))
    quarantines.extend(
        sidecar_rows_for_folder(
            folder,
            context,
            list(snapshot_contexts.values()),
            list(feature_support.values()),
        )
    )
    return dedupe_rows(quarantines), feature_support, count, item


def _scan_status(
    folder: Path,
    *,
    snapshot_ids: set[str],
    event_slug: str,
    summary_item: dict[str, Any] | None = None,
    long_item: dict[str, Any] | None = None,
) -> tuple[set[str], dict[str, int], list[dict[str, Any]]]:
    summary, summary_item = _read_small_json(
        folder / "replay_input_status.json",
        role="replay_status",
        item=summary_item,
    )
    path = folder / "replay_input_status_long.csv"
    long_item = long_item or _input(
        path,
        role="replay_status_tape",
        max_bytes=MAX_SNAPSHOT_BYTES,
    )
    statuses: dict[str, str] = {}
    for row_number, row in _iter_csv(path, role="replay_status_tape", max_bytes=MAX_SNAPSHOT_BYTES):
        snapshot_id = str(row.get("snapshot_id") or "").strip()
        status_value = str(row.get("replay_input_status") or "").strip()
        if not snapshot_id or snapshot_id in statuses:
            raise AdmissibilityBlock("replay_status_duplicate", f"replay status row {row_number} has a missing or duplicate snapshot_id")
        if snapshot_id not in snapshot_ids:
            raise AdmissibilityBlock("replay_status_unknown_snapshot", f"replay status references unknown snapshot {snapshot_id}")
        if row.get("event_slug") != event_slug:
            raise AdmissibilityBlock("replay_status_event_mismatch", f"replay status for {snapshot_id} has the wrong event_slug")
        if status_value not in {"captured", "evaluation_only", "reconstructed"}:
            raise AdmissibilityBlock("replay_status_invalid", f"replay status for {snapshot_id} is invalid: {status_value!r}")
        statuses[snapshot_id] = status_value
    if set(statuses) != snapshot_ids:
        raise AdmissibilityBlock("replay_status_incomplete", f"replay status covers {len(statuses)} of {len(snapshot_ids)} snapshots")
    counts = Counter(statuses.values())
    if counts.get("reconstructed", 0):
        raise AdmissibilityBlock("reconstructed_inputs_present", f"{counts['reconstructed']} snapshots are reconstructed")
    expected_counts = summary.get("counts")
    if (
        summary.get("snapshot_count") != len(snapshot_ids)
        or not isinstance(expected_counts, dict)
        or any(expected_counts.get(key, 0) != counts.get(key, 0) for key in set(expected_counts) | set(counts))
        or summary.get("captured_count") != counts.get("captured", 0)
        or summary.get("evaluation_only_count") != counts.get("evaluation_only", 0)
        or summary.get("reconstructed_count") != counts.get("reconstructed", 0)
    ):
        raise AdmissibilityBlock("replay_status_summary_mismatch", "replay status summary does not match its strict row tape")
    return {snapshot_id for snapshot_id, value in statuses.items() if value == "captured"}, dict(counts), [summary_item, long_item]


def _scan_replay(
    path: Path,
    *,
    snapshot_ids: set[str],
    captured_ids: set[str],
    event_slug: str,
    target_date: str,
    quarantines: list[dict[str, Any]],
    item: dict[str, Any] | None = None,
) -> tuple[set[str], set[str], dict[str, Any]]:
    item = item or _input(
        path,
        role="captured_input_tape",
        max_bytes=MAX_REPLAY_BYTES,
    )
    replay_ids: set[str] = set()
    contaminated: set[str] = set()
    quarantine_by_snapshot: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in quarantines:
        quarantine_by_snapshot[str(row.get("snapshot_id") or "")].append(row)
    try:
        with path.open("rb") as handle:
            for line_number, raw in enumerate(handle, start=1):
                if line_number > MAX_ROWS:
                    raise AdmissibilityBlock("replay_row_bound", f"captured-input tape exceeds {MAX_ROWS} rows")
                if len(raw) > MAX_LINE_BYTES:
                    raise AdmissibilityBlock("replay_line_bound", f"captured-input line {line_number} exceeds {MAX_LINE_BYTES} bytes")
                if not raw.strip():
                    continue
                try:
                    record = strict_json_loads(raw.decode("utf-8"), label=f"captured-input line {line_number}")
                except (UnicodeDecodeError, ValueError) as exc:
                    raise AdmissibilityBlock("replay_invalid_jsonl", f"captured-input line {line_number} is invalid: {exc}") from exc
                if not isinstance(record, dict):
                    raise AdmissibilityBlock("replay_invalid_jsonl", f"captured-input line {line_number} is not an object")
                snapshot_id = str(record.get("snapshot_id") or "").strip()
                if not snapshot_id or snapshot_id in replay_ids:
                    raise AdmissibilityBlock("replay_duplicate_snapshot", f"captured-input line {line_number} has a missing or duplicate snapshot_id")
                if snapshot_id not in snapshot_ids:
                    raise AdmissibilityBlock("replay_unknown_snapshot", f"captured-input tape references unknown snapshot {snapshot_id}")
                if record.get("event_slug") not in (None, "", event_slug):
                    raise AdmissibilityBlock("replay_event_mismatch", f"captured input {snapshot_id} has the wrong event_slug")
                if record.get("target_date") not in (None, "", target_date):
                    raise AdmissibilityBlock("replay_date_mismatch", f"captured input {snapshot_id} has the wrong target_date")
                source_values = {
                    str(record.get(key) or "").lower()
                    for key in ("replay_input_source", "source", "capture_source")
                }
                if any("reconstruct" in value for value in source_values):
                    raise AdmissibilityBlock("reconstructed_inputs_present", f"captured input {snapshot_id} is reconstructed")
                claimed = str(record.get("captured_input_hash") or "")
                try:
                    actual = captured_input_payload_sha256(record, persisted=True)
                except (ValueError, ReleaseArtifactVerificationError) as exc:
                    raise AdmissibilityBlock("replay_hash_invalid", f"captured input {snapshot_id} cannot be canonically hashed: {exc}") from exc
                if len(claimed) != 64 or claimed != actual:
                    raise AdmissibilityBlock("replay_hash_mismatch", f"captured input {snapshot_id} has an invalid self-hash")
                _validate_distribution(record, snapshot_id=snapshot_id)
                replay_ids.add(snapshot_id)
                for quarantine in quarantine_by_snapshot[snapshot_id]:
                    quarantine["replay_input_present"] = True
                    quarantine["replay_input_feature_contaminated"] = replay_feature_contaminated(record, quarantine)
                    if quarantine["replay_input_feature_contaminated"]:
                        contaminated.add(snapshot_id)
    except AdmissibilityBlock:
        raise
    except OSError as exc:
        raise AdmissibilityBlock("replay_unreadable", f"captured-input tape cannot be read: {path}") from exc
    if replay_ids != captured_ids:
        raise AdmissibilityBlock(
            "captured_input_inventory_mismatch",
            f"captured-input tape has {len(replay_ids)} records but status declares {len(captured_ids)} captured snapshots",
        )
    apply_recovery_classification(quarantines)
    excluded = {
        str(row.get("snapshot_id") or "")
        for row in quarantines
        if row.get("promotion_excluded") and row.get("snapshot_id")
    }
    return replay_ids, excluded | contaminated, item


def _validate_settlement_sidecar(
    folder: Path,
    *,
    label: Mapping[str, Any],
    event_slug: str,
    market_id: str,
    target_date: str,
    item: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, item = _read_small_json(
        folder / "settlement.json",
        role="settlement_sidecar",
        item=item,
    )
    expected = {
        "event_slug": event_slug,
        "market_id": market_id,
        "target_date": target_date,
        "settlement_unit": REGISTRY[market_id].display_unit,
        "winning_band": canonical_winning_band(label.get("winning_band")),
        "label_hash": label.get("label_hash"),
        "revision_id": label.get("revision_id"),
    }
    observed = {
        "event_slug": payload.get("event_slug"),
        "market_id": payload.get("market_id"),
        "target_date": payload.get("target_date"),
        "settlement_unit": payload.get("settlement_unit"),
        "winning_band": canonical_winning_band(payload.get("winning_band")),
        "label_hash": payload.get("label_hash"),
        "revision_id": payload.get("revision_id"),
    }
    if observed != expected:
        differences = [key for key in expected if observed[key] != expected[key]]
        raise AdmissibilityBlock("settlement_sidecar_mismatch", f"settlement sidecar differs from ledger fields: {differences}")
    return payload, item


def grade_market_day(
    *,
    target_date: date,
    snapshots_root: str | Path,
    ledger_root: str | Path,
    receipt_path: str | Path,
    market_id: str = DEFAULT_MARKET_ID,
) -> dict[str, Any]:
    """Stream one market-day and persist a PASS/BLOCK receipt."""

    if market_id not in REGISTRY:
        raise ValueError(f"unknown market_id: {market_id}")
    date_text = target_date.isoformat()
    event_slug = event_slug_for_date(target_date, market_id)
    snapshots_root = Path(snapshots_root).resolve()
    ledger_root = Path(ledger_root).resolve()
    folder = snapshots_root / event_slug
    receipt_path = Path(receipt_path)
    inputs: list[dict[str, Any]] = []
    inventory: dict[str, Any] = {}
    ledger_identity: dict[str, Any] = {}
    status = "BLOCK"
    reason = {"code": "not_evaluated", "detail": "evaluation did not run"}
    try:
        ledger_path = ledger_path_for_market(market_id, ledger_root)
        ledger_item = _input(
            ledger_path,
            role="settlement_ledger",
            max_bytes=MAX_LEDGER_BYTES,
        )
        inputs.append(ledger_item)
        label, verification, ledger_item = _read_ledger(
            ledger_path,
            event_slug=event_slug,
            market_id=market_id,
            item=ledger_item,
        )
        ledger_identity = {
            "revision_id": label.get("revision_id"),
            "revision_number": label.get("revision_number"),
            "label_hash": label.get("label_hash"),
            "quality_grade": label.get("quality_grade"),
            "winning_band": canonical_winning_band(label.get("winning_band")),
            "settlement_bucket": label.get("settlement_bucket"),
            "settlement_unit": label.get("settlement_unit"),
            "history_record_count": verification.get("record_count"),
        }
        try:
            folder_info = folder.lstat()
        except FileNotFoundError as exc:
            raise AdmissibilityBlock("snapshot_folder_missing", f"snapshot folder is missing: {folder}") from exc
        if stat.S_ISLNK(folder_info.st_mode) or not stat.S_ISDIR(folder_info.st_mode) or folder.name != event_slug:
            raise AdmissibilityBlock("snapshot_folder_identity", f"snapshot folder is not the exact regular directory for {event_slug}")
        sidecar_item = _input(
            folder / "settlement.json",
            role="settlement_sidecar",
            max_bytes=MAX_SMALL_JSON_BYTES,
        )
        inputs.append(sidecar_item)
        _sidecar, sidecar_item = _validate_settlement_sidecar(
            folder,
            label=label,
            event_slug=event_slug,
            market_id=market_id,
            target_date=date_text,
            item=sidecar_item,
        )
        snapshot_item = _input(
            folder / "snapshots_long.csv",
            role="snapshot_tape",
            max_bytes=MAX_SNAPSHOT_BYTES,
        )
        inputs.append(snapshot_item)
        snapshot_contexts, snapshot_rows, band_count, snapshot_item = _scan_snapshot_tape(
            folder / "snapshots_long.csv",
            target_date=date_text,
            event_slug=event_slug,
            label=label,
            item=snapshot_item,
        )
        feature_path = folder / "features_long.csv"
        feature_item = (
            _input(
                feature_path,
                role="feature_tape",
                max_bytes=MAX_FEATURE_BYTES,
            )
            if feature_path.exists()
            else None
        )
        if feature_item:
            inputs.append(feature_item)
        quarantines, _feature_support, feature_rows, feature_item = _scan_features(
            folder,
            unit=REGISTRY[market_id].display_unit,
            snapshot_contexts=snapshot_contexts,
            item=feature_item,
        )
        status_summary_item = _input(
            folder / "replay_input_status.json",
            role="replay_status",
            max_bytes=MAX_SMALL_JSON_BYTES,
        )
        status_long_item = _input(
            folder / "replay_input_status_long.csv",
            role="replay_status_tape",
            max_bytes=MAX_SNAPSHOT_BYTES,
        )
        inputs.extend((status_summary_item, status_long_item))
        captured_ids, status_counts, status_items = _scan_status(
            folder,
            snapshot_ids=set(snapshot_contexts),
            event_slug=event_slug,
            summary_item=status_summary_item,
            long_item=status_long_item,
        )
        replay_item = _input(
            folder / "replay_inputs.jsonl",
            role="captured_input_tape",
            max_bytes=MAX_REPLAY_BYTES,
        )
        inputs.append(replay_item)
        replay_ids, excluded_ids, replay_item = _scan_replay(
            folder / "replay_inputs.jsonl",
            snapshot_ids=set(snapshot_contexts),
            captured_ids=captured_ids,
            event_slug=event_slug,
            target_date=date_text,
            quarantines=quarantines,
            item=replay_item,
        )
        pinned_ids = captured_ids - excluded_ids
        if not pinned_ids:
            raise AdmissibilityBlock("no_release_admissible_inputs", "feature-quality quarantine excludes every captured input")
        inventory = {
            "snapshot_count": len(snapshot_contexts),
            "snapshot_row_count": snapshot_rows,
            "band_count": band_count,
            "feature_row_count": feature_rows,
            "captured_input_count": len(replay_ids),
            "evaluation_only_count": status_counts.get("evaluation_only", 0),
            "reconstructed_count": status_counts.get("reconstructed", 0),
            "feature_quality_quarantine_row_count": len(quarantines),
            "feature_quality_excluded_snapshot_count": len(excluded_ids),
            "release_admissible_snapshot_count": len(pinned_ids),
        }
        status = "PASS"
        reason = {"code": "release_admissible", "detail": "all production source checks passed"}
    except AdmissibilityBlock as exc:
        reason = {"code": exc.code, "detail": exc.detail}
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "artifact_type": RECEIPT_ARTIFACT_TYPE,
        "generated_at_utc": _now(),
        "market_id": market_id,
        "target_date": date_text,
        "event_slug": event_slug,
        "status": status,
        "reason": reason,
        "ledger": ledger_identity,
        "inventory": inventory,
        "inputs": sorted(inputs, key=lambda row: row["role"]),
    }
    receipt["receipt_sha256"] = _self_hash(receipt, "receipt_sha256")
    write_json_atomic(receipt_path, receipt)
    return receipt


def load_receipt(path: str | Path) -> dict[str, Any]:
    payload, _item = _read_small_json(Path(path), role="release_admissibility_receipt")
    if (
        payload.get("schema_version") != RECEIPT_SCHEMA_VERSION
        or payload.get("artifact_type") != RECEIPT_ARTIFACT_TYPE
        or payload.get("receipt_sha256") != _self_hash(payload, "receipt_sha256")
    ):
        raise AdmissibilityBlock("receipt_invalid", f"receipt identity or self-hash is invalid: {path}")
    return payload


def collapse_receipts(
    *,
    receipt_root: str | Path,
    clock_path: str | Path,
    market_id: str = DEFAULT_MARKET_ID,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Read only small receipts and collapse the most recent calendar streak."""

    root = Path(receipt_root)
    receipts: dict[date, dict[str, Any]] = {}
    if root.exists():
        for path in sorted(root.glob("*.json")):
            try:
                payload = load_receipt(path)
                parsed = date.fromisoformat(str(payload.get("target_date") or ""))
            except (AdmissibilityBlock, ValueError):
                continue
            if payload.get("market_id") == market_id:
                receipts[parsed] = payload
    requested_end = as_of or (max(receipts) if receipts else date.today())
    eligible_dates = [
        key
        for key, payload in receipts.items()
        if key <= requested_end
        and (payload.get("reason") or {}).get("code") != "ledger_label_missing"
    ]
    end = max(eligible_dates) if eligible_dates else requested_end
    streak_dates: list[date] = []
    cursor = end
    while (receipt := receipts.get(cursor)) is not None and receipt.get("status") == "PASS":
        streak_dates.append(cursor)
        cursor -= timedelta(days=1)
    recent = [
        {
            "target_date": key.isoformat(),
            "status": payload.get("status"),
            "reason_code": (payload.get("reason") or {}).get("code"),
            "receipt_sha256": payload.get("receipt_sha256"),
        }
        for key, payload in sorted(receipts.items())
    ]
    latest = receipts.get(end)
    clock: dict[str, Any] = {
        "schema_version": CLOCK_SCHEMA_VERSION,
        "artifact_type": CLOCK_ARTIFACT_TYPE,
        "generated_at_utc": _now(),
        "market_id": market_id,
        "as_of_date": requested_end.isoformat(),
        "evaluation_end_date": end.isoformat() if eligible_dates else None,
        "contiguous_pass_days": len(streak_dates),
        "streak_start_date": min(streak_dates).isoformat() if streak_dates else None,
        "latest_status": latest.get("status") if latest else "MISSING",
        "latest_reason_code": (latest.get("reason") or {}).get("code") if latest else "receipt_missing",
        "receipt_count": len(recent),
        "receipts": recent,
        "receipt_set_sha256": _canonical_hash(recent),
    }
    clock["clock_sha256"] = _self_hash(clock, "clock_sha256")
    write_json_atomic(clock_path, clock)
    return clock


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    grade = subparsers.add_parser("grade", help="grade one market-day and write its receipt")
    grade.add_argument("--target-date", required=True)
    grade.add_argument("--snapshots-root", required=True)
    grade.add_argument("--ledger-root", required=True)
    grade.add_argument("--receipt", required=True)
    grade.add_argument("--market-id", default=DEFAULT_MARKET_ID)
    grade.add_argument("--fail-on-block", action="store_true")
    date_range = subparsers.add_parser("grade-range", help="grade an inclusive date range, then collapse receipts")
    date_range.add_argument("--start-date", required=True)
    date_range.add_argument("--end-date", required=True)
    date_range.add_argument("--snapshots-root", required=True)
    date_range.add_argument("--ledger-root", required=True)
    date_range.add_argument("--receipt-root", required=True)
    date_range.add_argument("--clock-out", required=True)
    date_range.add_argument("--market-id", default=DEFAULT_MARKET_ID)
    date_range.add_argument("--fail-on-block", action="store_true")
    collapse = subparsers.add_parser("collapse", help="collapse small receipts without reading source tapes")
    collapse.add_argument("--receipt-root", required=True)
    collapse.add_argument("--clock-out", required=True)
    collapse.add_argument("--market-id", default=DEFAULT_MARKET_ID)
    collapse.add_argument("--as-of")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "grade":
        result = grade_market_day(
            target_date=date.fromisoformat(args.target_date),
            snapshots_root=args.snapshots_root,
            ledger_root=args.ledger_root,
            receipt_path=args.receipt,
            market_id=args.market_id,
        )
        print(json.dumps(result, sort_keys=True))
        return 2 if args.fail_on_block and result["status"] != "PASS" else 0
    if args.command == "collapse":
        result = collapse_receipts(
            receipt_root=args.receipt_root,
            clock_path=args.clock_out,
            market_id=args.market_id,
            as_of=date.fromisoformat(args.as_of) if args.as_of else None,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    if start > end:
        raise SystemExit("--start-date must be on or before --end-date")
    cursor = start
    results = []
    while cursor <= end:
        results.append(
            grade_market_day(
                target_date=cursor,
                snapshots_root=args.snapshots_root,
                ledger_root=args.ledger_root,
                receipt_path=Path(args.receipt_root) / f"{cursor.isoformat()}.json",
                market_id=args.market_id,
            )
        )
        cursor += timedelta(days=1)
    clock = collapse_receipts(
        receipt_root=args.receipt_root,
        clock_path=args.clock_out,
        market_id=args.market_id,
        as_of=end,
    )
    output = {
        "status": "PASS" if all(row["status"] == "PASS" for row in results) else "BLOCK",
        "receipts": [
            {"target_date": row["target_date"], "status": row["status"], "reason": row["reason"]}
            for row in results
        ],
        "clock": clock,
    }
    print(json.dumps(output, sort_keys=True))
    return 2 if args.fail_on_block and output["status"] != "PASS" else 0


if __name__ == "__main__":
    sys.exit(main())
