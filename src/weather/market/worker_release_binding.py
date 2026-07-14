"""Fail-closed release binding for model-consuming trading workers.

Maker and taker workers consume the snapshot projection rather than construct a
model themselves.  A verified active bundle is therefore necessary but not
sufficient evidence for their rows: the snapshot they consumed must also have
been captured by that exact bundle.  ``replay_inputs.jsonl`` is the independent,
self-hashed capture record that proves that link without trusting caller-supplied
lineage or copying identity from a served row.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from weather.market.market_config import config_for_date
from weather.market.market_microstructure_features import snapshot_band_key
from weather.paths import REPO_ROOT
from weather.release_artifacts import (
    DEFAULT_ACTIVE_RELEASE_POINTER,
    DEFAULT_RELEASES_ROOT,
    canonical_payload_sha256,
    strict_json_loads,
)
from weather.release_serving import (
    STATUS_BOUND,
    STATUS_RESEARCH_UNBOUND,
    VerifiedServingBundle,
    get_process_active_serving_bundle,
    serving_bundle_lineage,
)
from weather.schema_registry import schema_version


REPLAY_INPUT_FILENAME = "replay_inputs.jsonl"
VERIFIED_RELEASE_IDENTITY_STATUS = "verified_variant_serving_bundle"
CAPTURED_INPUT_HASH_ALGORITHM = "sha256-canonical-json;omit=captured_input_hash"
REPLAY_INPUT_SCHEMA_VERSION = schema_version("replay_inputs")
MAX_REPLAY_INPUT_LINE_BYTES = 8 * 1024 * 1024
SNAPSHOT_PROBABILITY_TOLERANCE = 1e-9
RECORDED_DISTRIBUTION_MASS_TOLERANCE = 1e-6
LINEAGE_FIELDS = (
    "release_id",
    "release_manifest_sha256",
    "release_pointer_sha256",
    "release_sequence",
    "release_identity_status",
    "release_identity_reason",
    "base_model_release_bound",
    "base_model_binding_reason",
)


class WorkerReleaseBindingError(RuntimeError):
    """A worker cannot prove that its model inputs belong to the active release."""


@dataclass(frozen=True)
class WorkerReleaseBinding:
    bundle: VerifiedServingBundle
    lineage: Mapping[str, Any]

    @property
    def release_bound(self) -> bool:
        return self.bundle.status == STATUS_BOUND and self.bundle.base_model_bound


def load_worker_release_binding(
    *,
    pointer_path: str | Path = DEFAULT_ACTIVE_RELEASE_POINTER,
    releases_root: str | Path = DEFAULT_RELEASES_ROOT,
    repo_root: str | Path = REPO_ROOT,
    check_runtime: bool = True,
    enabled: bool = True,
) -> WorkerReleaseBinding:
    """Load the process-sticky active bundle and reject an invalid active pointer."""

    if enabled:
        bundle = get_process_active_serving_bundle(
            pointer_path=pointer_path,
            releases_root=releases_root,
            repo_root=repo_root,
            check_runtime=check_runtime,
        )
    else:
        bundle = VerifiedServingBundle(
            status=STATUS_RESEARCH_UNBOUND,
            reason=(
                "non-default worker snapshot root has no explicit active-release pointer; "
                "diagnostic output is release-unbound and non-countable"
            ),
            pointer_present=False,
        )
    if bundle.status not in {STATUS_BOUND, STATUS_RESEARCH_UNBOUND} or (
        bundle.status == STATUS_BOUND and not bundle.base_model_bound
    ) or (bundle.pointer_present and bundle.status != STATUS_BOUND):
        raise WorkerReleaseBindingError(
            "active release state cannot provide the worker's complete process-sticky "
            f"verified serving bundle: status={bundle.status}; reason={bundle.reason}"
        )
    return WorkerReleaseBinding(
        bundle=bundle,
        lineage=dict(serving_bundle_lineage(bundle)),
    )


def _normalized_target_date(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def _snapshot_expectations(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, str]]:
    expectations: dict[str, dict[str, str]] = {}
    for row in rows:
        snapshot_id = str(row.get("snapshot_id") or "").strip()
        if not snapshot_id:
            raise WorkerReleaseBindingError(
                "release-bound worker input contains a snapshot row without snapshot_id"
            )
        expectation = {
            "event_slug": str(row.get("event_slug") or ""),
            "captured_at_utc": str(row.get("captured_at_utc") or ""),
            "model_version": str(row.get("model_version") or ""),
        }
        previous = expectations.setdefault(snapshot_id, expectation)
        if previous != expectation:
            raise WorkerReleaseBindingError(
                f"snapshot {snapshot_id!r} has internally inconsistent identity fields"
            )
    return expectations


def _matching_replay_inputs(
    path: Path,
    snapshot_ids: set[str],
) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                if len(line.encode("utf-8")) > MAX_REPLAY_INPUT_LINE_BYTES:
                    raise WorkerReleaseBindingError(
                        f"captured-input tape row exceeds the bounded line ceiling at "
                        f"{path}:{line_number}"
                    )
                try:
                    row = strict_json_loads(
                        text,
                        label=f"captured-input tape {path}:{line_number}",
                    )
                except ValueError as exc:
                    raise WorkerReleaseBindingError(
                        f"captured-input tape is invalid JSON at {path}:{line_number}: {exc}"
                    ) from exc
                if not isinstance(row, dict):
                    raise WorkerReleaseBindingError(
                        f"captured-input tape row is not an object at {path}:{line_number}"
                    )
                snapshot_id = str(row.get("snapshot_id") or "")
                if snapshot_id not in snapshot_ids:
                    continue
                previous = found.get(snapshot_id)
                if previous is not None and previous != row:
                    raise WorkerReleaseBindingError(
                        f"captured-input tape has conflicting rows for snapshot {snapshot_id!r}"
                    )
                found[snapshot_id] = row
    except OSError as exc:
        raise WorkerReleaseBindingError(
            f"captured-input tape cannot be read for release-bound worker inputs: {path}: {exc}"
        ) from exc
    return found


def _verify_captured_input_hash(record: Mapping[str, Any], *, snapshot_id: str) -> None:
    claimed = str(record.get("captured_input_hash") or "")
    unhashed = dict(record)
    unhashed.pop("captured_input_hash", None)
    actual = canonical_payload_sha256(unhashed)
    if len(claimed) != 64 or claimed != actual:
        raise WorkerReleaseBindingError(
            f"captured-input self-hash mismatch for snapshot {snapshot_id!r}"
        )


def _recorded_distribution(
    record: Mapping[str, Any],
    *,
    snapshot_id: str,
) -> dict[int, float]:
    raw = record.get("recorded_distribution")
    if not isinstance(raw, Mapping) or not raw:
        raise WorkerReleaseBindingError(
            "captured-input proof has no recorded_distribution for worker snapshot "
            f"{snapshot_id!r}; recapture complete release-bound inputs"
        )
    distribution: dict[int, float] = {}
    for raw_bucket, raw_probability in raw.items():
        try:
            numeric_bucket = float(raw_bucket)
            bucket = int(numeric_bucket)
            probability = float(raw_probability)
        except (TypeError, ValueError, OverflowError) as exc:
            raise WorkerReleaseBindingError(
                "captured-input recorded_distribution contains a non-numeric bucket or "
                f"probability for snapshot {snapshot_id!r}"
            ) from exc
        if (
            not math.isfinite(numeric_bucket)
            or numeric_bucket != bucket
            or not math.isfinite(probability)
            or probability < 0.0
            or probability > 1.0
            or bucket in distribution
        ):
            raise WorkerReleaseBindingError(
                "captured-input recorded_distribution is not a canonical finite bucket "
                f"distribution for snapshot {snapshot_id!r}"
            )
        distribution[bucket] = probability
    total_mass = sum(distribution.values())
    if abs(total_mass - 1.0) > RECORDED_DISTRIBUTION_MASS_TOLERANCE:
        raise WorkerReleaseBindingError(
            "captured-input recorded_distribution does not preserve probability mass "
            f"for snapshot {snapshot_id!r}: total={total_mass:.12g}"
        )
    return distribution


def _verify_snapshot_band_probabilities(
    rows: Iterable[Mapping[str, Any]],
    record: Mapping[str, Any],
    *,
    snapshot_id: str,
) -> None:
    """Authenticate consumed band probabilities against the hashed capture canary."""

    distribution = _recorded_distribution(record, snapshot_id=snapshot_id)
    for row_number, row in enumerate(rows, start=1):
        kind, value, value_hi = snapshot_band_key(row)
        if kind not in {"lte", "eq", "gte"} or value is None:
            raise WorkerReleaseBindingError(
                "worker snapshot contains an invalid band identity while verifying "
                f"recorded_distribution for snapshot {snapshot_id!r}, row {row_number}"
            )
        upper = value if value_hi is None else value_hi
        if kind == "lte":
            expected = sum(
                probability
                for bucket, probability in distribution.items()
                if bucket <= value
            )
        elif kind == "gte":
            expected = sum(
                probability
                for bucket, probability in distribution.items()
                if bucket >= value
            )
        else:
            expected = sum(
                probability
                for bucket, probability in distribution.items()
                if value <= bucket <= upper
            )
        try:
            stored = float(row.get("model_probability"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise WorkerReleaseBindingError(
                "worker snapshot model_probability is missing or invalid for "
                f"snapshot {snapshot_id!r}, row {row_number}"
            ) from exc
        if (
            not math.isfinite(stored)
            or stored < 0.0
            or stored > 1.0
            or abs(stored - expected) > SNAPSHOT_PROBABILITY_TOLERANCE
        ):
            raise WorkerReleaseBindingError(
                "worker snapshot model_probability does not match the self-hashed "
                f"recorded_distribution for snapshot {snapshot_id!r}, row {row_number}: "
                f"stored={stored:.12g}; expected={expected:.12g}"
            )


def verify_worker_snapshot_binding(
    folder: str | Path,
    snapshot_rows: Iterable[Mapping[str, Any]],
    binding: WorkerReleaseBinding,
    *,
    market_id: str,
    target_date: Any,
) -> None:
    """Prove that snapshot rows were captured under the worker's verified bundle.

    Research-unbound operation remains available and explicitly non-countable.
    Once an active pointer exists, every consumed snapshot must have an exact,
    self-hashed replay-input record under the same release, manifest, pointer,
    route, target date, and base-model binding.
    """

    rows = list(snapshot_rows)
    if not rows or not binding.release_bound:
        return

    routes = binding.bundle.route.get("markets")
    route = routes.get(market_id) if isinstance(routes, Mapping) else None
    if (
        not isinstance(route, Mapping)
        or route.get("decision") not in {"promote", "shadow"}
        or route.get("base_model_market_id") != market_id
    ):
        raise WorkerReleaseBindingError(
            "verified active release has no complete serving route for worker market "
            f"{market_id!r}"
        )

    expected_event_slug = config_for_date(target_date, market_id).event_slug
    input_folder = Path(folder)
    if input_folder.name != expected_event_slug:
        raise WorkerReleaseBindingError(
            "release-bound worker snapshot folder does not match the requested market-day: "
            f"expected {expected_event_slug!r}, got {input_folder.name!r}"
        )

    expectations = _snapshot_expectations(rows)
    rows_by_snapshot: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        rows_by_snapshot.setdefault(str(row.get("snapshot_id") or ""), []).append(row)
    replay_path = Path(folder) / REPLAY_INPUT_FILENAME
    if not replay_path.is_file():
        raise WorkerReleaseBindingError(
            "verified active release requires captured-input proof for every worker snapshot; "
            f"missing {replay_path}"
        )
    records = _matching_replay_inputs(replay_path, set(expectations))
    missing = sorted(set(expectations) - set(records))
    if missing:
        raise WorkerReleaseBindingError(
            f"captured-input tape {replay_path} has no row for worker snapshots: {missing}"
        )

    target = _normalized_target_date(target_date)
    for snapshot_id, expectation in expectations.items():
        record = records[snapshot_id]
        _verify_captured_input_hash(record, snapshot_id=snapshot_id)
        checks = {
            "schema_version": record.get("schema_version")
            == REPLAY_INPUT_SCHEMA_VERSION,
            "release_id": str(record.get("release_id") or "")
            == binding.bundle.release_id,
            "release_manifest_sha256": str(
                record.get("release_manifest_sha256") or ""
            )
            == binding.bundle.manifest_sha256,
            "release_pointer_sha256": str(record.get("release_pointer_sha256") or "")
            == binding.bundle.pointer_sha256,
            "release_sequence": record.get("release_sequence") == binding.bundle.sequence,
            "release_identity_status": record.get("release_identity_status")
            == VERIFIED_RELEASE_IDENTITY_STATUS,
            "base_model_release_bound": record.get("base_model_release_bound") is True,
            "captured_input_hash_algorithm": record.get("captured_input_hash_algorithm")
            == CAPTURED_INPUT_HASH_ALGORITHM,
            "target_date": str(record.get("target_date") or "") == target,
            "snapshot_event_slug": expectation["event_slug"]
            == expected_event_slug,
            "event_slug": str(record.get("event_slug") or "")
            == expected_event_slug,
            "captured_at_utc": str(record.get("captured_at_utc") or "")
            == expectation["captured_at_utc"],
            "model_version": str(record.get("model_version") or "")
            == expectation["model_version"],
        }
        failed = sorted(name for name, ok in checks.items() if not ok)
        if failed:
            raise WorkerReleaseBindingError(
                "captured-input proof does not match the verified active serving bundle "
                f"for snapshot {snapshot_id!r}; failed fields: {', '.join(failed)}"
            )
        _verify_snapshot_band_probabilities(
            rows_by_snapshot[snapshot_id],
            record,
            snapshot_id=snapshot_id,
        )


def stamp_worker_release_lineage(
    rows: Iterable[dict[str, Any]],
    binding: WorkerReleaseBinding,
) -> None:
    """Stamp only lineage derived from the opaque verified bundle loader."""

    lineage = {field: binding.lineage.get(field) for field in LINEAGE_FIELDS}
    for row in rows:
        row.update(lineage)


def worker_tape_columns(
    base_columns: Iterable[str],
    binding: WorkerReleaseBinding,
) -> list[str]:
    """Add lineage columns only to release-bound tape contracts.

    Research-unbound workers retain the historical column contract, so an
    ordinary code deployment cannot invalidate an in-progress incremental
    tape.  Activation is boundary-aware: a bound worker requires a fresh or
    already release-aware tape and fails closed instead of rewriting evidence.
    """

    columns = list(base_columns)
    if binding.release_bound:
        columns.extend(field for field in LINEAGE_FIELDS if field not in columns)
    return columns


def worker_tape_columns_from_rows(
    base_columns: Iterable[str],
    rows: Iterable[Mapping[str, Any]],
) -> list[str]:
    """Preserve verified lineage when deriving a settled tape contract.

    Finalization has no active-bundle dependency: it derives the singular
    identity from the immutable source rows.  Legacy research-unbound rows keep
    the exact historical header, while any incomplete or mixed bound identity
    fails closed through ``worker_tape_summary_fields``.
    """

    materialized = rows if isinstance(rows, list) else list(rows)
    lineage = worker_tape_summary_fields(materialized)
    columns = list(base_columns)
    if lineage.get("release_id"):
        columns.extend(field for field in LINEAGE_FIELDS if field not in columns)
    return columns


def _expected_lineage(binding: WorkerReleaseBinding) -> dict[str, Any]:
    return {field: binding.lineage.get(field) for field in LINEAGE_FIELDS}


def _present_lineage_fields(row: Mapping[str, Any]) -> set[str]:
    return {field for field in LINEAGE_FIELDS if field in row}


def _lineage_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    return None


def _lineage_value_matches(field: str, actual: Any, expected: Any) -> bool:
    if field == "base_model_release_bound":
        return _lineage_bool(actual) is bool(expected)
    if field == "release_sequence":
        return str(actual or "") == str(expected or "")
    return str(actual or "") == str(expected or "")


def _lineage_identity_value(field: str, value: Any) -> str:
    if field == "base_model_release_bound":
        parsed = _lineage_bool(value)
        return str(parsed).lower() if parsed is not None else str(value or "")
    return str(value or "")


def _valid_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(
        character in "0123456789abcdef" for character in text.lower()
    )


def verify_worker_tape_lineage(
    rows: Iterable[Mapping[str, Any]],
    binding: WorkerReleaseBinding,
    *,
    label: str,
) -> None:
    """Reject appends that would mix release-bound and unbound identities."""

    expected = _expected_lineage(binding)
    for index, row in enumerate(rows, start=1):
        present_fields = _present_lineage_fields(row)
        if not present_fields and not binding.release_bound:
            # Historical research tapes predate lineage columns entirely.
            # They remain valid diagnostic evidence, but a partially added
            # lineage contract must never be mistaken for that legacy shape.
            continue
        failed = sorted(
            field
            for field in LINEAGE_FIELDS
            if field not in present_fields
            or not _lineage_value_matches(field, row.get(field), expected.get(field))
        )
        if failed:
            raise WorkerReleaseBindingError(
                f"{label} row {index} does not match the current verified serving "
                f"bundle; failed fields: {', '.join(failed)}"
            )


def verify_worker_csv_tape_for_append(
    path: str | Path,
    columns: Iterable[str],
    binding: WorkerReleaseBinding,
    *,
    label: str,
) -> None:
    """Stream-verify an existing tape's header and singular release identity."""

    tape = Path(path)
    if not tape.exists() or tape.stat().st_size == 0:
        return
    try:
        with tape.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if list(reader.fieldnames or []) != list(columns):
                raise WorkerReleaseBindingError(
                    f"{label} column contract does not match the current release "
                    "binding; start a fresh boundary run instead of rewriting the tape"
                )
            verify_worker_tape_lineage(reader, binding, label=label)
    except OSError as exc:
        raise WorkerReleaseBindingError(f"cannot verify {label}: {tape}: {exc}") from exc


def worker_tape_summary_fields(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Recover one singular lineage from a persisted worker tape."""

    rows = list(rows)
    required_fields = set(LINEAGE_FIELDS)
    presence = [_present_lineage_fields(row) for row in rows]
    partial = [
        index
        for index, fields in enumerate(presence, start=1)
        if fields and fields != required_fields
    ]
    if partial:
        raise WorkerReleaseBindingError(
            "worker tape contains incomplete release lineage at rows "
            f"{partial[:10]}; refusing summary recovery"
        )
    if any(fields == required_fields for fields in presence) and any(
        not fields for fields in presence
    ):
        raise WorkerReleaseBindingError(
            "worker tape mixes legacy no-lineage rows with stamped release lineage; "
            "refusing summary recovery"
        )
    if not rows or all(not fields for fields in presence):
        lineage = {
            field: "" if field != "release_sequence" else None
            for field in LINEAGE_FIELDS
        }
        lineage.update(
            release_identity_status="research_unbound_non_countable",
            release_identity_reason="recovered tape has no verified release identity",
            base_model_release_bound=False,
            base_model_binding_reason="recovered tape is release-unbound",
        )
        return {**lineage, "release_identity": dict(lineage)}

    identities = {
        tuple(
            _lineage_identity_value(field, row.get(field))
            for field in LINEAGE_FIELDS
        )
        for row in rows
    }
    if len(identities) > 1:
        raise WorkerReleaseBindingError(
            "worker tape contains mixed release identities; refusing summary recovery"
        )
    values = next(iter(identities))
    lineage = dict(zip(LINEAGE_FIELDS, values))
    bound_value = _lineage_bool(lineage["base_model_release_bound"])
    if bound_value is None:
        raise WorkerReleaseBindingError(
            "worker tape base-model release binding flag is invalid during summary recovery"
        )
    lineage["base_model_release_bound"] = bound_value
    if lineage["release_id"]:
        try:
            lineage["release_sequence"] = int(lineage["release_sequence"])
        except (TypeError, ValueError) as exc:
            raise WorkerReleaseBindingError(
                "worker tape release sequence is invalid during summary recovery"
            ) from exc
        if (
            not _valid_sha256(lineage["release_manifest_sha256"])
            or not _valid_sha256(lineage["release_pointer_sha256"])
            or lineage["release_identity_status"]
            != VERIFIED_RELEASE_IDENTITY_STATUS
            or lineage["base_model_release_bound"] is not True
            or not lineage["release_identity_reason"]
            or not lineage["base_model_binding_reason"]
        ):
            raise WorkerReleaseBindingError(
                "worker tape release identity is incomplete or unverified during "
                "summary recovery"
            )
    else:
        if (
            lineage["release_manifest_sha256"]
            or lineage["release_pointer_sha256"]
            or lineage["release_sequence"]
            or lineage["release_identity_status"]
            != "research_unbound_non_countable"
            or not lineage["release_identity_reason"]
            or lineage["base_model_release_bound"] is not False
        ):
            raise WorkerReleaseBindingError(
                "worker tape research-unbound lineage is incomplete or inconsistent "
                "during summary recovery"
            )
        lineage["release_sequence"] = None
    return {**lineage, "release_identity": dict(lineage)}


def worker_release_summary_fields(binding: WorkerReleaseBinding) -> dict[str, Any]:
    lineage = {field: binding.lineage.get(field) for field in LINEAGE_FIELDS}
    return {
        **lineage,
        "release_kind": binding.bundle.release_kind,
        "release_candidate_mode": binding.bundle.candidate_mode,
        "release_production_capable": binding.bundle.production_capable,
        "release_identity": dict(lineage),
    }
