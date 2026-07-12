"""Point-in-time analytical contract and bounded evaluation utilities.

The module deliberately separates three concerns:

* ``materialize`` reads one market-day at a time through the validated
  Parquet/text fallback reader and writes a derived, hash-addressed Parquet
  table without changing source evidence;
* ``folds`` builds fleet-date rolling-origin folds with a calendar-day embargo
  and fresh, training-only hook instances; and
* ``evaluate`` streams a locked window into market-day summaries before any
  weighting or date-clustered bootstrap is performed.

Rows from weather-only models, the market benchmark, market-informed overlays,
and trading evidence are never pooled into one estimate.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import random
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Protocol, Sequence

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from weather.backtesting.settled_days import discover_settled_folders, folder_market_id
from weather.market.market_config import date_from_event_slug
from weather.operations.closed_market_day_archive import (
    DEFAULT_ARCHIVE_ROOT,
    DEFAULT_SNAPSHOTS_ROOT,
    read_market_day_artifact,
)
from weather.paths import data_path
from weather.schema_registry import schema_version


CONTRACT_SCHEMA_VERSION = schema_version("point_in_time_analytical_contract")
MATERIALIZER_SCHEMA_VERSION = schema_version("point_in_time_materializer")
VALIDATION_PLAN_SCHEMA_VERSION = schema_version("point_in_time_validation_plan")
FIT_RECEIPT_SCHEMA_VERSION = schema_version("point_in_time_fit_receipt")
EVALUATION_SCHEMA_VERSION = schema_version("point_in_time_streaming_evaluation")
TRANSFORMATION_VERSION = MATERIALIZER_SCHEMA_VERSION

DEFAULT_DERIVED_ROOT = data_path("analysis", "point_in_time", "v0.1")
DEFAULT_PARQUET_OUT = DEFAULT_DERIVED_ROOT / "point_in_time_rows.parquet"
DEFAULT_MANIFEST_OUT = DEFAULT_DERIVED_ROOT / "point_in_time_manifest.json"
DEFAULT_EVALUATION_OUT = data_path("backtest", "point_in_time_streaming_evaluation.json")
DEFAULT_FOLDS_OUT = data_path("backtest", "point_in_time_validation_plan.json")

KEY_FIELDS = (
    "target_date",
    "market_id",
    "cutoff_or_snapshot",
    "band",
    "variant_id",
    "release_id",
)
CLAIM_LANES = (
    "weather_only",
    "market_benchmark",
    "market_informed",
    "trading",
)
COUNTABLE_LABEL_QUALITIES = frozenset({"complete", "manual_override"})
NONCOUNTABLE_LABEL_QUALITIES = frozenset({"incomplete", "quarantined", "missing"})
LABEL_QUALITIES = COUNTABLE_LABEL_QUALITIES | NONCOUNTABLE_LABEL_QUALITIES
PARITY_STATES = frozenset({"pass", "fail", "unverified", "not_applicable"})
COUNTABLE_SOURCE_QUALITIES = frozenset({"healthy", "complete"})
SOURCE_QUALITIES = COUNTABLE_SOURCE_QUALITIES | frozenset(
    {"degraded", "stale", "failed", "unknown"}
)
LANES_REQUIRING_PARITY = frozenset({"weather_only", "market_informed"})
REQUIRED_FIT_STAGES = (
    "feature_selection",
    "scaling_imputation",
    "model",
    "calibration",
    "postprocessing",
    "regime_router",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

LANE_ALIASES = {
    "weather_only": "weather_only",
    "weather-only": "weather_only",
    "weather_only_core_model": "weather_only",
    "weather_only_quote_risk_diagnostic": "weather_only",
    "model": "weather_only",
    "market": "market_benchmark",
    "market_benchmark": "market_benchmark",
    "market-benchmark": "market_benchmark",
    "market_informed": "market_informed",
    "market-informed": "market_informed",
    "market_informed_overlay": "market_informed",
    "market_informed_quote_risk": "market_informed",
    "trading": "trading",
    "paper_trading": "trading",
    "execution": "trading",
    "maker": "trading",
    "taker": "trading",
}

POINT_IN_TIME_ARROW_SCHEMA = pa.schema(
    [
        pa.field("schema_version", pa.string(), nullable=False),
        *(pa.field(field, pa.string(), nullable=False) for field in KEY_FIELDS),
        pa.field("source_payload_json", pa.string(), nullable=False),
        pa.field("source_payload_sha256", pa.string(), nullable=False),
        pa.field("source_provenance_json", pa.string(), nullable=False),
        pa.field("feature_available_at_utc", pa.string(), nullable=False),
        pa.field("prediction_made_at_utc", pa.string(), nullable=False),
        pa.field("label_quality", pa.string(), nullable=False),
        pa.field("countable", pa.bool_(), nullable=False),
        pa.field("claim_lane", pa.string(), nullable=False),
        pa.field("replay_serve_parity", pa.string(), nullable=False),
        pa.field("source_quality", pa.string(), nullable=False),
        pa.field("transformation_version", pa.string(), nullable=False),
        pa.field("prediction_probability", pa.float64(), nullable=True),
        pa.field("label", pa.float64(), nullable=True),
        pa.field("runtime_identity", pa.string(), nullable=False),
    ]
)


class ContractViolation(ValueError):
    """A fail-closed point-in-time row validation error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class BoundedReadError(RuntimeError):
    """A configured market-day streaming bound was exceeded."""


class TrainingOnlyHook(Protocol):
    """Minimal leakage-safe fold hook used for preprocessing through routing."""

    def fit(self, rows: Sequence[Mapping[str, Any]]) -> Any: ...

    def transform(
        self, rows: Sequence[Mapping[str, Any]]
    ) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class RollingOriginFold:
    fold_id: str
    train_dates: tuple[str, ...]
    embargo_dates: tuple[str, ...]
    validation_dates: tuple[str, ...]
    embargo_days: int


@dataclass(frozen=True)
class NestedRollingOriginFold:
    outer: RollingOriginFold
    inner: tuple[RollingOriginFold, ...]


@dataclass(frozen=True)
class FoldPipelineResult:
    fold_id: str
    train_dates: tuple[str, ...]
    validation_dates: tuple[str, ...]
    stage_names: tuple[str, ...]
    train_rows: tuple[Mapping[str, Any], ...]
    validation_rows: tuple[Mapping[str, Any], ...]
    fit_receipts: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class MarketDayMetric:
    target_date: str
    market_id: str
    claim_lane: str
    variant_id: str
    release_id: str
    categorical_brier: float
    categorical_log_loss: float
    cutoff_count: int
    row_count: int
    runtime_identity: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generated_at_utc(value: str | None) -> str:
    return _parse_utc(value or _utc_now_iso(), "generated_at_utc").isoformat()


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, set):
        converted = [_jsonable(item) for item in value]
        return sorted(
            converted,
            key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False),
        )
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, bool) and missing:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def canonical_json(value: Any) -> str:
    """Return deterministic JSON used for both payload persistence and hashing."""

    return json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _finalize_hash(payload: Mapping[str, Any], field: str) -> dict[str, Any]:
    finalized = _jsonable(payload)
    finalized.pop(field, None)
    finalized[field] = sha256_text(canonical_json(finalized))
    return finalized


def _verify_self_hash(payload: Mapping[str, Any], field: str, code: str) -> None:
    actual = str(payload.get(field) or "")
    unhashed = dict(payload)
    unhashed.pop(field, None)
    if not SHA256_RE.fullmatch(actual) or actual != sha256_text(canonical_json(unhashed)):
        raise ContractViolation(code, f"{field} is missing or invalid")


def _optional_identity(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} cannot be blank")
    return normalized


def _atomic_write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        try:
            if bool(pd.isna(value)):
                continue
        except (TypeError, ValueError):
            pass
        return value
    return None


def _required_text(value: Any, code: str, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ContractViolation(code, f"{field} is required")
    return text


def _parse_utc(value: Any, field: str) -> datetime:
    text = _required_text(value, f"missing_{field}", field)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ContractViolation(f"invalid_{field}", f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ContractViolation(f"naive_{field}", f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _parse_date(value: Any, field: str = "target_date") -> date:
    text = _required_text(value, f"missing_{field}", field)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ContractViolation(f"invalid_{field}", f"{field} must be YYYY-MM-DD") from exc


def _strict_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    raise ContractViolation(f"invalid_{field}", f"{field} must be boolean")


def _optional_float(value: Any, field: str) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractViolation(f"invalid_{field}", f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ContractViolation(f"invalid_{field}", f"{field} must be finite")
    return number


def normalize_claim_lane(value: Any) -> str:
    text = str(value or "").strip().lower()
    lane = LANE_ALIASES.get(text)
    if lane is None:
        raise ContractViolation(
            "invalid_claim_lane",
            f"claim_lane must map to one of {', '.join(CLAIM_LANES)}",
        )
    return lane


def _normalize_parity(value: Any) -> str:
    text = str(value or "unverified").strip().lower().replace("-", "_")
    if text not in PARITY_STATES:
        raise ContractViolation("invalid_replay_serve_parity", "unknown parity state")
    return text


def _normalize_label_quality(value: Any) -> str:
    text = str(value or "missing").strip().lower().replace("-", "_")
    if text not in LABEL_QUALITIES:
        raise ContractViolation("invalid_label_quality", "unknown label quality")
    return text


def _normalize_source_quality(value: Any) -> str:
    text = str(value or "unknown").strip().lower().replace("-", "_")
    if text not in SOURCE_QUALITIES:
        raise ContractViolation("invalid_source_quality", "unknown source quality")
    return text


def _normalized_label(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    label = _optional_float(value, "label")
    if label is not None and label not in {0.0, 1.0}:
        raise ContractViolation("invalid_label", "label must be binary")
    return label


def canonicalize_raw_row(
    row: Mapping[str, Any],
    *,
    provenance: Mapping[str, Any],
    target_date: str | None = None,
    market_id: str | None = None,
    explicit_claim_lane: str | None = None,
    transformation_version: str = TRANSFORMATION_VERSION,
) -> dict[str, Any]:
    """Convert one source row without inventing missing release/label lineage."""

    payload_json = canonical_json(row)
    provenance_json = canonical_json(provenance)
    prediction_time = _first(
        row,
        "prediction_made_at_utc",
        "captured_at_utc",
        "evaluated_at_utc",
    )
    feature_time = _first(
        row,
        "feature_available_at_utc",
        "features_available_at_utc",
        "captured_at_utc",
    )
    canonical = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "target_date": target_date or _first(row, "target_date", "local_date"),
        "market_id": market_id or _first(row, "market_id", "location_id"),
        "cutoff_or_snapshot": _first(
            row,
            "cutoff_or_snapshot",
            "snapshot_id",
            "cutoff",
            "captured_at_utc",
        ),
        "band": _first(row, "band", "range_label", "band_label"),
        "variant_id": _first(row, "variant_id", "model_variant_id", "model_version"),
        "release_id": _first(row, "release_id"),
        "source_payload_json": payload_json,
        "source_payload_sha256": sha256_text(payload_json),
        "source_provenance_json": provenance_json,
        "feature_available_at_utc": feature_time,
        "prediction_made_at_utc": prediction_time,
        "label_quality": _first(row, "label_quality", "settlement_quality") or "missing",
        "countable": _first(row, "countable", "is_countable"),
        "claim_lane": explicit_claim_lane or _first(row, "claim_lane", "evidence_lane"),
        "replay_serve_parity": _first(
            row,
            "replay_serve_parity",
            "replay_serve_parity_status",
            "parity_status",
        )
        or "unverified",
        "source_quality": _first(row, "source_quality", "source_status_quality") or "unknown",
        "transformation_version": transformation_version,
        "prediction_probability": _first(
            row,
            "prediction_probability",
            "model_probability",
            "probability",
        ),
        "label": _first(row, "label", "is_winner", "settled_label"),
        "runtime_identity": _first(
            row,
            "runtime_identity",
            "runtime_source_fingerprint",
            "runtime_git_commit",
        )
        or "",
    }
    if canonical["countable"] is None:
        canonical["countable"] = False
    return validate_canonical_row(canonical)


def validate_canonical_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one analytical row under the v0.1 contract."""

    if row.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        raise ContractViolation("invalid_schema_version", "unexpected analytical row schema")

    normalized = dict(row)
    _parse_date(row.get("target_date"))
    for field in KEY_FIELDS:
        normalized[field] = _required_text(
            row.get(field), f"missing_{field}", field
        )

    payload_value = row.get("source_payload_json")
    if not isinstance(payload_value, str) or not payload_value.strip():
        raise ContractViolation("missing_source_payload", "source_payload_json is required")
    payload_json = payload_value
    try:
        parsed_payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise ContractViolation("invalid_source_payload", "source payload is not JSON") from exc
    if canonical_json(parsed_payload) != payload_json:
        raise ContractViolation(
            "noncanonical_source_payload", "source payload JSON is not canonical"
        )
    payload_hash = _required_text(
        row.get("source_payload_sha256"),
        "missing_source_payload_sha256",
        "source_payload_sha256",
    )
    if payload_hash != sha256_text(payload_json):
        raise ContractViolation("source_payload_hash_mismatch", "source payload hash mismatch")

    provenance_value = row.get("source_provenance_json")
    if not isinstance(provenance_value, str) or not provenance_value.strip():
        raise ContractViolation(
            "missing_source_provenance", "source_provenance_json is required"
        )
    provenance_json = provenance_value
    try:
        provenance = json.loads(provenance_json)
    except json.JSONDecodeError as exc:
        raise ContractViolation("invalid_source_provenance", "source provenance is not JSON") from exc
    if not isinstance(provenance, dict) or not str(provenance.get("source_mode") or "").strip():
        raise ContractViolation(
            "missing_source_mode", "source provenance must identify source_mode"
        )
    if canonical_json(provenance) != provenance_json:
        raise ContractViolation(
            "noncanonical_source_provenance", "source provenance JSON is not canonical"
        )

    feature_time = _parse_utc(row.get("feature_available_at_utc"), "feature_available_at_utc")
    prediction_time = _parse_utc(row.get("prediction_made_at_utc"), "prediction_made_at_utc")
    if feature_time > prediction_time:
        raise ContractViolation(
            "feature_available_after_prediction",
            "feature availability cannot be later than prediction time",
        )

    normalized["source_payload_json"] = payload_json
    normalized["source_payload_sha256"] = payload_hash
    normalized["source_provenance_json"] = provenance_json
    normalized["feature_available_at_utc"] = feature_time.isoformat()
    normalized["prediction_made_at_utc"] = prediction_time.isoformat()
    normalized["label_quality"] = _normalize_label_quality(row.get("label_quality"))
    normalized["countable"] = _strict_bool(row.get("countable"), "countable")
    normalized["claim_lane"] = normalize_claim_lane(row.get("claim_lane"))
    normalized["replay_serve_parity"] = _normalize_parity(row.get("replay_serve_parity"))
    normalized["source_quality"] = _normalize_source_quality(row.get("source_quality"))
    normalized["transformation_version"] = _required_text(
        row.get("transformation_version"),
        "missing_transformation_version",
        "transformation_version",
    )
    normalized["prediction_probability"] = _optional_float(
        row.get("prediction_probability"), "prediction_probability"
    )
    if (
        normalized["prediction_probability"] is not None
        and not 0.0 <= normalized["prediction_probability"] <= 1.0
    ):
        raise ContractViolation(
            "invalid_prediction_probability", "prediction probability must be in [0, 1]"
        )
    normalized["label"] = _normalized_label(row.get("label"))
    normalized["runtime_identity"] = _required_text(
        row.get("runtime_identity"), "missing_runtime_identity", "runtime_identity"
    )

    if normalized["countable"]:
        if normalized["label_quality"] not in COUNTABLE_LABEL_QUALITIES:
            raise ContractViolation(
                "countable_label_quality_mismatch",
                "countable rows require complete or manual_override labels",
            )
        if normalized["prediction_probability"] is None or normalized["label"] is None:
            raise ContractViolation(
                "countable_score_fields_missing",
                "countable rows require prediction_probability and label",
            )
    return {field.name: normalized.get(field.name) for field in POINT_IN_TIME_ARROW_SCHEMA}


def point_in_time_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(row[field]) for field in KEY_FIELDS)


def _folder_sort_key(folder: str | Path) -> tuple[str, str, str]:
    path = Path(folder)
    target = date_from_event_slug(path.name)
    return (
        target.isoformat() if target else "9999-12-31",
        str(folder_market_id(path) or ""),
        path.name,
    )


def _frame_rows(frame: pd.DataFrame) -> Iterator[dict[str, Any]]:
    columns = [str(column) for column in frame.columns]
    for values in frame.itertuples(index=False, name=None):
        yield dict(zip(columns, values, strict=True))


def materialize_point_in_time_table(
    folders: Iterable[str | Path],
    *,
    parquet_out: str | Path = DEFAULT_PARQUET_OUT,
    manifest_out: str | Path = DEFAULT_MANIFEST_OUT,
    artifact_family: str = "snapshots_long",
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    archive_root: str | Path = DEFAULT_ARCHIVE_ROOT,
    archive_as_of_date: str | date | datetime | None = None,
    prefer_archive: bool = True,
    explicit_claim_lane: str | None = None,
    max_market_days: int = 500,
    max_rows_per_market_day: int = 250_000,
    generated_at_utc: str | None = None,
    candidate_id: str | None = None,
    release_id: str | None = None,
) -> dict[str, Any]:
    """Write canonical rows while retaining at most one source market-day.

    Source evidence is only read. The derived Parquet file is written through
    a temporary path and committed atomically after its manifest statistics
    have been computed.
    """

    if max_market_days <= 0 or max_rows_per_market_day <= 0:
        raise ValueError("streaming bounds must be positive")
    ordered_folders = sorted((Path(folder) for folder in folders), key=_folder_sort_key)
    if len(ordered_folders) > max_market_days:
        raise BoundedReadError(
            f"market-day bound exceeded: {len(ordered_folders)} > {max_market_days}"
        )

    parquet_out = Path(parquet_out)
    manifest_out = Path(manifest_out)
    parquet_out.parent.mkdir(parents=True, exist_ok=True)
    temp_out = parquet_out.with_name(f".{parquet_out.name}.{os.getpid()}.tmp")
    if temp_out.exists():
        temp_out.unlink()

    writer: pq.ParquetWriter | None = None
    accepted_rows = 0
    source_rows = 0
    exclusions: Counter[str] = Counter()
    source_modes: Counter[str] = Counter()
    label_qualities: Counter[str] = Counter()
    claim_lanes: Counter[str] = Counter()
    input_rows: list[dict[str, Any]] = []
    seen_market_days: set[tuple[str, str]] = set()

    try:
        for folder in ordered_folders:
            target = date_from_event_slug(folder.name)
            market = folder_market_id(folder)
            if target is None or market is None:
                exclusions["unknown_market_day_folder"] += 1
                continue
            market_day = (target.isoformat(), market)
            if market_day in seen_market_days:
                raise BoundedReadError(f"duplicate market-day folder: {market_day}")
            seen_market_days.add(market_day)

            result = read_market_day_artifact(
                folder,
                artifact_family,
                snapshots_root=snapshots_root,
                archive_root=archive_root,
                as_of_date=archive_as_of_date,
                prefer_archive=prefer_archive,
            )
            frame_rows = len(result.frame)
            if frame_rows > max_rows_per_market_day:
                raise BoundedReadError(
                    f"row bound exceeded for {folder.name}: "
                    f"{frame_rows} > {max_rows_per_market_day}"
                )
            source_rows += frame_rows
            provenance = asdict(result.provenance)
            source_modes[str(provenance.get("source_mode") or "unknown")] += 1
            input_rows.append(
                {
                    "folder": str(folder),
                    "target_date": market_day[0],
                    "market_id": market_day[1],
                    "artifact_family": artifact_family,
                    "source_mode": provenance.get("source_mode"),
                    "source_row_count": frame_rows,
                    "source_file_hash": provenance.get("source_file_hash"),
                    "parquet_file_hash": provenance.get("parquet_file_hash"),
                    "manifest_hash": provenance.get("manifest_hash"),
                    "fallback_reason": provenance.get("fallback_reason"),
                }
            )

            day_rows: list[dict[str, Any]] = []
            day_keys: set[tuple[str, ...]] = set()
            for row_index, raw_row in enumerate(_frame_rows(result.frame)):
                row_provenance = {**provenance, "source_row_index": row_index}
                try:
                    canonical = canonicalize_raw_row(
                        raw_row,
                        provenance=row_provenance,
                        target_date=market_day[0],
                        market_id=market_day[1],
                        explicit_claim_lane=explicit_claim_lane,
                    )
                    key = point_in_time_key(canonical)
                    if key in day_keys:
                        raise ContractViolation(
                            "duplicate_point_in_time_key",
                            "duplicate analytical key within market-day",
                        )
                    day_keys.add(key)
                except ContractViolation as exc:
                    exclusions[exc.code] += 1
                    continue
                day_rows.append(canonical)
                label_qualities[canonical["label_quality"]] += 1
                claim_lanes[canonical["claim_lane"]] += 1

            day_rows.sort(key=point_in_time_key)
            if day_rows:
                table = pa.Table.from_pylist(day_rows, schema=POINT_IN_TIME_ARROW_SCHEMA)
                if writer is None:
                    writer = pq.ParquetWriter(
                        temp_out,
                        POINT_IN_TIME_ARROW_SCHEMA,
                        compression="zstd",
                    )
                writer.write_table(table)
                accepted_rows += len(day_rows)
    except BaseException:
        if writer is not None:
            writer.close()
            writer = None
        if temp_out.exists():
            temp_out.unlink()
        raise
    finally:
        if writer is not None:
            writer.close()

    if not temp_out.exists():
        pq.write_table(
            pa.Table.from_pylist([], schema=POINT_IN_TIME_ARROW_SCHEMA),
            temp_out,
            compression="zstd",
        )
    os.replace(temp_out, parquet_out)

    status = "PASS"
    if accepted_rows == 0 or exclusions:
        status = "BLOCK"
    manifest = {
        "schema_version": MATERIALIZER_SCHEMA_VERSION,
        "artifact_type": "point_in_time_materialization_manifest",
        "generated_at_utc": _generated_at_utc(generated_at_utc),
        "status": status,
        "row_key": list(KEY_FIELDS),
        "claim_lane_contract": list(CLAIM_LANES),
        "raw_evidence_mutated": False,
        "derived_artifact": {
            "path": str(parquet_out),
            "sha256": sha256_file(parquet_out),
            "row_count": accepted_rows,
            "bytes": parquet_out.stat().st_size,
            "compression": "zstd",
        },
        "transformation": {
            "version": TRANSFORMATION_VERSION,
            "source_artifact_family": artifact_family,
            "source_reader": "weather.operations.closed_market_day_archive.read_market_day_artifact",
            "source_reader_order": [
                "validated_parquet",
                "gzip_tiered_text",
                "text_tape",
            ],
        },
        "streaming_bounds": {
            "max_market_days": max_market_days,
            "max_rows_per_market_day": max_rows_per_market_day,
            "raw_market_days_retained_at_once": 1,
        },
        "counts": {
            "market_days_read": len(input_rows),
            "source_rows": source_rows,
            "accepted_rows": accepted_rows,
            "excluded_rows": sum(exclusions.values()),
            "exclusions_by_reason": dict(sorted(exclusions.items())),
            "source_modes": dict(sorted(source_modes.items())),
            "label_qualities": dict(sorted(label_qualities.items())),
            "claim_lanes": dict(sorted(claim_lanes.items())),
        },
        "inputs": input_rows,
    }
    normalized_candidate = _optional_identity(candidate_id, "candidate_id")
    normalized_release = _optional_identity(release_id, "release_id")
    if normalized_candidate is not None:
        manifest["candidate_id"] = normalized_candidate
    if normalized_release is not None:
        manifest["release_id"] = normalized_release
    manifest["manifest_hash"] = sha256_text(canonical_json(manifest))
    _atomic_write_json(manifest_out, manifest)
    return manifest


def verify_materialization_manifest(
    parquet_path: str | Path,
    manifest_path: str | Path,
    *,
    expected_candidate_id: str | None = None,
    expected_release_id: str | None = None,
) -> dict[str, Any]:
    parquet_path = Path(parquet_path)
    manifest_path = Path(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractViolation("invalid_materialization_manifest", str(exc)) from exc
    if manifest.get("schema_version") != MATERIALIZER_SCHEMA_VERSION:
        raise ContractViolation("invalid_materialization_manifest", "schema mismatch")
    if manifest.get("artifact_type") != "point_in_time_materialization_manifest":
        raise ContractViolation("invalid_materialization_manifest", "artifact type mismatch")
    manifest_hash = str(manifest.get("manifest_hash") or "")
    unhashed_manifest = dict(manifest)
    unhashed_manifest.pop("manifest_hash", None)
    if manifest_hash != sha256_text(canonical_json(unhashed_manifest)):
        raise ContractViolation(
            "materialization_manifest_hash_mismatch", "manifest hash mismatch"
        )
    if manifest.get("status") != "PASS":
        raise ContractViolation(
            "materialization_not_pass", "materialization manifest is not PASS"
        )
    artifact = manifest.get("derived_artifact") or {}
    if artifact.get("sha256") != sha256_file(parquet_path):
        raise ContractViolation("materialization_hash_mismatch", "Parquet hash mismatch")
    actual_rows = int(pq.ParquetFile(parquet_path).metadata.num_rows)
    if int(artifact.get("row_count") or -1) != actual_rows:
        raise ContractViolation("materialization_row_count_mismatch", "row count mismatch")
    if expected_candidate_id is not None and manifest.get("candidate_id") != expected_candidate_id:
        raise ContractViolation(
            "materialization_candidate_identity_mismatch",
            "materialization candidate identity mismatch",
        )
    if expected_release_id is not None and manifest.get("release_id") != expected_release_id:
        raise ContractViolation(
            "materialization_release_identity_mismatch",
            "materialization release identity mismatch",
        )
    return manifest


def iter_point_in_time_parquet(
    path: str | Path,
    *,
    batch_rows: int = 65_536,
) -> Iterator[dict[str, Any]]:
    """Yield bounded canonical Parquet batches without retaining the corpus."""

    if batch_rows <= 0:
        raise ValueError("batch_rows must be positive")
    parquet = pq.ParquetFile(path)
    missing = set(POINT_IN_TIME_ARROW_SCHEMA.names) - set(parquet.schema_arrow.names)
    if missing:
        raise ContractViolation(
            "missing_analytical_columns", f"missing columns: {sorted(missing)}"
        )
    for batch in parquet.iter_batches(
        batch_size=batch_rows,
        columns=POINT_IN_TIME_ARROW_SCHEMA.names,
    ):
        yield from batch.to_pylist()


def iter_point_in_time_jsonl(
    path: str | Path,
    *,
    max_line_bytes: int = 4 * 1024 * 1024,
) -> Iterator[dict[str, Any]]:
    """Yield canonical JSONL rows with a hard per-row byte bound."""

    path = Path(path)
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if len(line.encode("utf-8")) > max_line_bytes:
                raise BoundedReadError(f"line {line_no} exceeds max_line_bytes")
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ContractViolation("invalid_jsonl_row", f"line {line_no}") from exc
            if not isinstance(row, dict):
                raise ContractViolation("invalid_jsonl_row", f"line {line_no}")
            yield row


def _unique_dates(values: Iterable[str | date]) -> list[date]:
    parsed = {
        value if isinstance(value, date) else _parse_date(value, "fleet_date")
        for value in values
    }
    return sorted(parsed)


def build_rolling_origin_folds(
    fleet_dates: Iterable[str | date],
    *,
    min_train_dates: int,
    validation_dates: int = 1,
    embargo_days: int = 3,
    step_dates: int = 1,
) -> tuple[RollingOriginFold, ...]:
    """Build expanding folds whose membership is always an entire fleet date."""

    if not 3 <= embargo_days <= 7:
        raise ValueError("embargo_days must be between 3 and 7")
    if min_train_dates <= 0 or validation_dates <= 0 or step_dates <= 0:
        raise ValueError("fold sizes and step_dates must be positive")
    dates = _unique_dates(fleet_dates)
    folds: list[RollingOriginFold] = []
    for start in range(0, len(dates), step_dates):
        validation = dates[start : start + validation_dates]
        if len(validation) != validation_dates:
            break
        first_validation = validation[0]
        train = [
            item
            for item in dates[:start]
            if (first_validation - item).days > embargo_days
        ]
        if len(train) < min_train_dates:
            continue
        embargo = [
            item
            for item in dates[:start]
            if 0 < (first_validation - item).days <= embargo_days
        ]
        fold_number = len(folds) + 1
        folds.append(
            RollingOriginFold(
                fold_id=f"rolling_origin_{fold_number:03d}",
                train_dates=tuple(item.isoformat() for item in train),
                embargo_dates=tuple(item.isoformat() for item in embargo),
                validation_dates=tuple(item.isoformat() for item in validation),
                embargo_days=embargo_days,
            )
        )
    return tuple(folds)


def build_nested_rolling_origin_folds(
    fleet_dates: Iterable[str | date],
    *,
    outer_min_train_dates: int,
    inner_min_train_dates: int,
    outer_validation_dates: int = 1,
    inner_validation_dates: int = 1,
    embargo_days: int = 3,
    step_dates: int = 1,
) -> tuple[NestedRollingOriginFold, ...]:
    """Build inner folds solely from each outer fold's training dates."""

    outer_folds = build_rolling_origin_folds(
        fleet_dates,
        min_train_dates=outer_min_train_dates,
        validation_dates=outer_validation_dates,
        embargo_days=embargo_days,
        step_dates=step_dates,
    )
    nested: list[NestedRollingOriginFold] = []
    for outer in outer_folds:
        inner = build_rolling_origin_folds(
            outer.train_dates,
            min_train_dates=inner_min_train_dates,
            validation_dates=inner_validation_dates,
            embargo_days=embargo_days,
            step_dates=step_dates,
        )
        nested.append(NestedRollingOriginFold(outer=outer, inner=inner))
    return tuple(nested)


def _fold_scope_rows(
    nested: Sequence[NestedRollingOriginFold],
) -> dict[str, RollingOriginFold]:
    scopes: dict[str, RollingOriginFold] = {}
    for item in nested:
        outer_scope = f"outer/{item.outer.fold_id}"
        scopes[outer_scope] = item.outer
        for inner in item.inner:
            scopes[f"{outer_scope}/inner/{inner.fold_id}"] = inner
    return scopes


def build_fit_receipt(
    fold: RollingOriginFold,
    *,
    fold_scope: str,
    stage_name: str,
    implementation_identity: str,
    fit_rows: Sequence[Mapping[str, Any]],
    validation_rows: Sequence[Mapping[str, Any]],
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build a hash-linked receipt proving a stage saw training rows only."""

    scope = str(fold_scope).strip()
    stage = str(stage_name).strip()
    implementation = str(implementation_identity).strip()
    if not scope or not stage or not implementation:
        raise ValueError("fold_scope, stage_name, and implementation_identity are required")
    if not fit_rows or not validation_rows:
        raise ValueError("fit and validation receipt rows cannot be empty")
    fit_dates = {str(row.get("target_date") or "") for row in fit_rows}
    validation_dates = {str(row.get("target_date") or "") for row in validation_rows}
    if fit_dates != set(fold.train_dates) or validation_dates != set(fold.validation_dates):
        raise ContractViolation(
            "fit_receipt_date_mismatch",
            "fit receipt rows do not exactly match the declared fold",
        )
    receipt = {
        "schema_version": FIT_RECEIPT_SCHEMA_VERSION,
        "artifact_type": "training_only_fit_receipt",
        "generated_at_utc": _generated_at_utc(generated_at_utc),
        "fold_scope": scope,
        "fold_id": fold.fold_id,
        "stage_name": stage,
        "implementation_identity": implementation,
        "fit_scope": "training_only",
        "train_dates": list(fold.train_dates),
        "embargo_dates": list(fold.embargo_dates),
        "validation_dates": list(fold.validation_dates),
        "embargo_days": fold.embargo_days,
        "fit_row_count": len(fit_rows),
        "validation_row_count": len(validation_rows),
        "fit_input_sha256": sha256_text(canonical_json([_jsonable(row) for row in fit_rows])),
        "validation_input_sha256": sha256_text(
            canonical_json([_jsonable(row) for row in validation_rows])
        ),
    }
    return _finalize_hash(receipt, "receipt_sha256")


def run_training_only_pipeline(
    fold: RollingOriginFold,
    rows_by_date: Mapping[str, Sequence[Mapping[str, Any]]],
    hook_factories: Sequence[tuple[str, Callable[[], TrainingOnlyHook]]],
    *,
    fold_scope: str | None = None,
    generated_at_utc: str | None = None,
) -> FoldPipelineResult:
    """Fit fresh preprocessing/model/calibration/router hooks on training only.

    Each factory is called once per fold. ``fit`` only receives rows from
    ``fold.train_dates``; validation rows are exposed solely through
    ``transform`` after the fit completes. This one interface covers feature
    selection, scaling/imputation, model fitting, calibration, postprocessing,
    and predeclared regime-router selection.
    """

    def rows_for_dates(target_dates: Sequence[str]) -> tuple[Mapping[str, Any], ...]:
        selected: list[Mapping[str, Any]] = []
        for target_date in target_dates:
            for row in rows_by_date.get(target_date, ()):
                if str(row.get("target_date") or "") != target_date:
                    raise ContractViolation(
                        "fleet_date_bucket_mismatch",
                        f"row target_date does not match bucket {target_date}",
                    )
                selected.append(row)
        return tuple(selected)

    train_rows = rows_for_dates(fold.train_dates)
    validation_rows = rows_for_dates(fold.validation_dates)
    if not train_rows:
        raise ValueError("training fold has no rows")
    if not validation_rows:
        raise ValueError("validation fold has no rows")

    stage_names: list[str] = []
    fitted_hooks: list[TrainingOnlyHook] = []
    fit_receipts: list[Mapping[str, Any]] = []
    train_state = train_rows
    validation_state = validation_rows
    for name, factory in hook_factories:
        if not str(name).strip():
            raise ValueError("training-only hook name is required")
        hook = factory()
        if hook is None:
            raise ValueError(f"hook factory returned None: {name}")
        hook.fit(train_state)
        fit_receipts.append(
            build_fit_receipt(
                fold,
                fold_scope=fold_scope or f"outer/{fold.fold_id}",
                stage_name=str(name),
                implementation_identity=(
                    f"{type(hook).__module__}.{type(hook).__qualname__}"
                ),
                fit_rows=train_state,
                validation_rows=validation_state,
                generated_at_utc=generated_at_utc,
            )
        )
        train_state = tuple(hook.transform(train_state))
        validation_state = tuple(hook.transform(validation_state))
        fitted_hooks.append(hook)
        stage_names.append(str(name))
    return FoldPipelineResult(
        fold_id=fold.fold_id,
        train_dates=fold.train_dates,
        validation_dates=fold.validation_dates,
        stage_names=tuple(stage_names),
        train_rows=train_state,
        validation_rows=validation_state,
        fit_receipts=tuple(fit_receipts),
    )


def validation_plan_payload(
    fleet_dates: Iterable[str | date],
    *,
    outer_min_train_dates: int,
    inner_min_train_dates: int,
    outer_validation_dates: int = 1,
    inner_validation_dates: int = 1,
    embargo_days: int = 3,
    step_dates: int = 1,
    generated_at_utc: str | None = None,
    candidate_id: str | None = None,
    release_id: str | None = None,
    corpus_sha256: str | None = None,
    materialization_manifest_hash: str | None = None,
    fit_receipts: Sequence[Mapping[str, Any]] = (),
    required_fit_stages: Sequence[str] = REQUIRED_FIT_STAGES,
) -> dict[str, Any]:
    dates = _unique_dates(fleet_dates)
    nested = build_nested_rolling_origin_folds(
        dates,
        outer_min_train_dates=outer_min_train_dates,
        inner_min_train_dates=inner_min_train_dates,
        outer_validation_dates=outer_validation_dates,
        inner_validation_dates=inner_validation_dates,
        embargo_days=embargo_days,
        step_dates=step_dates,
    )
    inner_complete = bool(nested) and all(item.inner for item in nested)
    fold_scopes = _fold_scope_rows(nested)
    stages = tuple(str(stage).strip() for stage in required_fit_stages)
    if not stages or any(not stage for stage in stages) or len(stages) != len(set(stages)):
        raise ValueError("required_fit_stages must be unique non-empty names")
    receipts = [_jsonable(receipt) for receipt in fit_receipts]
    payload = {
        "schema_version": VALIDATION_PLAN_SCHEMA_VERSION,
        "artifact_type": "point_in_time_validation_plan",
        "generated_at_utc": _generated_at_utc(generated_at_utc),
        "status": "PASS" if inner_complete else "BLOCK",
        "independent_unit": "fleet_target_date",
        "grouping_rule": "all markets, bands, cutoffs, and variants for a fleet date remain together",
        "fit_boundary": (
            "feature selection, scaling/imputation, model, calibration, postprocessing, "
            "and router hooks fit on each training fold only"
        ),
        "config": {
            "outer_min_train_dates": outer_min_train_dates,
            "inner_min_train_dates": inner_min_train_dates,
            "outer_validation_dates": outer_validation_dates,
            "inner_validation_dates": inner_validation_dates,
            "embargo_days": embargo_days,
            "step_dates": step_dates,
        },
        "fleet_dates": [item.isoformat() for item in dates],
        "blockers": (
            []
            if inner_complete
            else ["no outer folds or at least one outer fold has no inner training fold"]
        ),
        "folds": [
            {
                "outer": asdict(item.outer),
                "inner": [asdict(fold) for fold in item.inner],
            }
            for item in nested
        ],
        "fit_receipt_contract": {
            "fit_scope": "training_only",
            "required_stages": list(stages),
            "required_fold_scopes": sorted(fold_scopes),
            "receipt_hash_field": "receipt_sha256",
        },
        "fit_receipts": receipts,
    }
    normalized_candidate = _optional_identity(candidate_id, "candidate_id")
    normalized_release = _optional_identity(release_id, "release_id")
    if normalized_candidate is not None:
        payload["candidate_id"] = normalized_candidate
    if normalized_release is not None:
        payload["release_id"] = normalized_release
    if corpus_sha256 is not None or materialization_manifest_hash is not None:
        payload["corpus_binding"] = {
            "corpus_sha256": str(corpus_sha256 or ""),
            "materialization_manifest_hash": str(materialization_manifest_hash or ""),
        }
    return _finalize_hash(payload, "plan_hash")


def _validated_fold_payload(
    payload: Mapping[str, Any], *, label: str
) -> RollingOriginFold:
    try:
        fold = RollingOriginFold(
            fold_id=_required_text(payload.get("fold_id"), "invalid_validation_plan", "fold_id"),
            train_dates=tuple(str(value) for value in payload.get("train_dates") or ()),
            embargo_dates=tuple(str(value) for value in payload.get("embargo_dates") or ()),
            validation_dates=tuple(str(value) for value in payload.get("validation_dates") or ()),
            embargo_days=int(payload.get("embargo_days")),
        )
    except (TypeError, ValueError) as exc:
        raise ContractViolation("invalid_validation_plan", f"{label} is malformed") from exc
    if not fold.train_dates or not fold.validation_dates or not 3 <= fold.embargo_days <= 7:
        raise ContractViolation("invalid_validation_plan", f"{label} has invalid fold sizes")
    all_dates = fold.train_dates + fold.embargo_dates + fold.validation_dates
    if len(all_dates) != len(set(all_dates)):
        raise ContractViolation("invalid_validation_plan", f"{label} overlaps date partitions")
    for value in all_dates:
        _parse_date(value, f"{label}.fleet_date")
    first_validation = _parse_date(fold.validation_dates[0], f"{label}.validation_date")
    if any(
        (first_validation - _parse_date(value, f"{label}.train_date")).days
        <= fold.embargo_days
        for value in fold.train_dates
    ):
        raise ContractViolation("invalid_validation_plan", f"{label} violates embargo")
    return fold


def verify_validation_plan_payload(
    payload: Mapping[str, Any],
    *,
    expected_candidate_id: str | None = None,
    expected_release_id: str | None = None,
    expected_corpus_sha256: str | None = None,
    expected_manifest_hash: str | None = None,
    expected_fleet_dates: Iterable[str] | None = None,
    require_fit_receipts: bool = False,
) -> dict[str, Any]:
    """Validate a frozen rolling-origin plan and its training-only receipts."""

    if payload.get("schema_version") != VALIDATION_PLAN_SCHEMA_VERSION:
        raise ContractViolation("invalid_validation_plan", "schema mismatch")
    if payload.get("artifact_type") != "point_in_time_validation_plan":
        raise ContractViolation("invalid_validation_plan", "artifact type mismatch")
    _verify_self_hash(payload, "plan_hash", "validation_plan_hash_mismatch")
    if payload.get("status") != "PASS":
        raise ContractViolation("validation_plan_not_pass", "validation plan is not PASS")
    _parse_utc(payload.get("generated_at_utc"), "validation_plan.generated_at_utc")
    if payload.get("independent_unit") != "fleet_target_date":
        raise ContractViolation("invalid_validation_plan", "independent unit mismatch")
    config = payload.get("config")
    if not isinstance(config, Mapping) or not 3 <= int(config.get("embargo_days") or 0) <= 7:
        raise ContractViolation("invalid_validation_plan", "embargo configuration is invalid")
    if expected_candidate_id is not None and payload.get("candidate_id") != expected_candidate_id:
        raise ContractViolation("validation_plan_identity_mismatch", "candidate identity mismatch")
    if expected_release_id is not None and payload.get("release_id") != expected_release_id:
        raise ContractViolation("validation_plan_identity_mismatch", "release identity mismatch")
    binding = payload.get("corpus_binding")
    if expected_corpus_sha256 is not None or expected_manifest_hash is not None:
        if not isinstance(binding, Mapping):
            raise ContractViolation("validation_plan_corpus_mismatch", "corpus binding is missing")
        if binding.get("corpus_sha256") != expected_corpus_sha256:
            raise ContractViolation("validation_plan_corpus_mismatch", "corpus hash mismatch")
        if binding.get("materialization_manifest_hash") != expected_manifest_hash:
            raise ContractViolation("validation_plan_corpus_mismatch", "manifest hash mismatch")

    fleet_dates = tuple(str(value) for value in payload.get("fleet_dates") or ())
    if not fleet_dates or len(fleet_dates) != len(set(fleet_dates)):
        raise ContractViolation("invalid_validation_plan", "fleet date inventory is invalid")
    for value in fleet_dates:
        _parse_date(value, "validation_plan.fleet_date")
    if expected_fleet_dates is not None and set(fleet_dates) != {
        str(value) for value in expected_fleet_dates
    }:
        raise ContractViolation(
            "validation_plan_corpus_mismatch", "fleet dates do not match the frozen corpus"
        )

    folds = payload.get("folds")
    if not isinstance(folds, list) or not folds:
        raise ContractViolation("invalid_validation_plan", "rolling-origin folds are missing")
    scopes: dict[str, RollingOriginFold] = {}
    for index, row in enumerate(folds):
        if not isinstance(row, Mapping) or not isinstance(row.get("outer"), Mapping):
            raise ContractViolation("invalid_validation_plan", f"fold {index} is malformed")
        outer = _validated_fold_payload(row["outer"], label=f"folds[{index}].outer")
        outer_scope = f"outer/{outer.fold_id}"
        if outer_scope in scopes:
            raise ContractViolation("invalid_validation_plan", "duplicate outer fold")
        scopes[outer_scope] = outer
        inner_rows = row.get("inner")
        if not isinstance(inner_rows, list) or not inner_rows:
            raise ContractViolation("invalid_validation_plan", "nested inner folds are missing")
        for inner_index, inner_row in enumerate(inner_rows):
            if not isinstance(inner_row, Mapping):
                raise ContractViolation("invalid_validation_plan", "inner fold is malformed")
            inner = _validated_fold_payload(
                inner_row, label=f"folds[{index}].inner[{inner_index}]"
            )
            if not set(inner.train_dates + inner.embargo_dates + inner.validation_dates) <= set(
                outer.train_dates
            ):
                raise ContractViolation(
                    "invalid_validation_plan", "inner fold escapes outer training dates"
                )
            scope = f"{outer_scope}/inner/{inner.fold_id}"
            if scope in scopes:
                raise ContractViolation("invalid_validation_plan", "duplicate inner fold")
            scopes[scope] = inner

    receipt_contract = payload.get("fit_receipt_contract")
    if not isinstance(receipt_contract, Mapping):
        raise ContractViolation("invalid_fit_receipts", "fit receipt contract is missing")
    stages = tuple(str(value) for value in receipt_contract.get("required_stages") or ())
    declared_scopes = tuple(str(value) for value in receipt_contract.get("required_fold_scopes") or ())
    if (
        receipt_contract.get("fit_scope") != "training_only"
        or receipt_contract.get("receipt_hash_field") != "receipt_sha256"
        or set(declared_scopes) != set(scopes)
    ):
        raise ContractViolation("invalid_fit_receipts", "fit receipt contract is inconsistent")
    if require_fit_receipts and set(stages) != set(REQUIRED_FIT_STAGES):
        raise ContractViolation("invalid_fit_receipts", "required fit stage inventory is incomplete")
    receipts = payload.get("fit_receipts")
    if not isinstance(receipts, list):
        raise ContractViolation("invalid_fit_receipts", "fit receipts are missing")
    receipt_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            raise ContractViolation("invalid_fit_receipts", "fit receipt is malformed")
        _verify_self_hash(receipt, "receipt_sha256", "fit_receipt_hash_mismatch")
        scope = str(receipt.get("fold_scope") or "")
        stage = str(receipt.get("stage_name") or "")
        key = (scope, stage)
        if key in receipt_by_key:
            raise ContractViolation("invalid_fit_receipts", "duplicate fit receipt")
        fold = scopes.get(scope)
        if (
            fold is None
            or stage not in stages
            or receipt.get("schema_version") != FIT_RECEIPT_SCHEMA_VERSION
            or receipt.get("artifact_type") != "training_only_fit_receipt"
            or receipt.get("fit_scope") != "training_only"
            or receipt.get("fold_id") != fold.fold_id
            or tuple(receipt.get("train_dates") or ()) != fold.train_dates
            or tuple(receipt.get("embargo_dates") or ()) != fold.embargo_dates
            or tuple(receipt.get("validation_dates") or ()) != fold.validation_dates
            or receipt.get("embargo_days") != fold.embargo_days
            or not str(receipt.get("implementation_identity") or "").strip()
            or int(receipt.get("fit_row_count") or 0) <= 0
            or int(receipt.get("validation_row_count") or 0) <= 0
            or not SHA256_RE.fullmatch(str(receipt.get("fit_input_sha256") or ""))
            or not SHA256_RE.fullmatch(str(receipt.get("validation_input_sha256") or ""))
        ):
            raise ContractViolation("invalid_fit_receipts", f"fit receipt is invalid: {key}")
        receipt_by_key[key] = receipt
    expected_keys = {(scope, stage) for scope in scopes for stage in stages}
    if require_fit_receipts and set(receipt_by_key) != expected_keys:
        raise ContractViolation(
            "invalid_fit_receipts", "fit receipts do not cover every fold and stage"
        )
    return dict(payload)


@dataclass
class _CutoffAccumulator:
    claim_lane: str
    variant_id: str
    release_id: str
    cutoff_or_snapshot: str
    probabilities: list[float]
    labels: list[float]
    bands: set[str]
    runtime_identities: set[str]

    @classmethod
    def create(cls, row: Mapping[str, Any]) -> _CutoffAccumulator:
        return cls(
            claim_lane=str(row["claim_lane"]),
            variant_id=str(row["variant_id"]),
            release_id=str(row["release_id"]),
            cutoff_or_snapshot=str(row["cutoff_or_snapshot"]),
            probabilities=[],
            labels=[],
            bands=set(),
            runtime_identities=set(),
        )

    def add(self, row: Mapping[str, Any]) -> None:
        band = str(row["band"])
        if band in self.bands:
            raise ContractViolation(
                "duplicate_band_within_cutoff", "band is duplicated within cutoff"
            )
        self.bands.add(band)
        self.probabilities.append(float(row["prediction_probability"]))
        self.labels.append(float(row["label"]))
        self.runtime_identities.add(str(row["runtime_identity"]))


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quantile requires values")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def date_clustered_bootstrap_interval(
    rows: Sequence[MarketDayMetric],
    *,
    metric: str,
    iterations: int = 2_000,
    seed: int = 31_415,
    confidence: float = 0.95,
    weighting: str = "equal_market_day",
) -> dict[str, Any]:
    """Bootstrap whole fleet dates while retaining every market in a cluster."""

    if metric not in {"categorical_brier", "categorical_log_loss"}:
        raise ValueError("unsupported metric")
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    if weighting not in {"equal_market_day", "equal_fleet_date"}:
        raise ValueError("unknown weighting")
    by_date: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_date[row.target_date].append(float(getattr(row, metric)))
    dates = sorted(by_date)
    if not dates:
        raise ValueError("bootstrap requires at least one fleet date")

    salt = f"{metric}|{weighting}|{'|'.join(dates)}"
    stable_seed = seed ^ int(sha256_text(salt)[:16], 16)
    rng = random.Random(stable_seed)
    replicates: list[float] = []
    for _ in range(iterations):
        sampled = [dates[rng.randrange(len(dates))] for _ in dates]
        if weighting == "equal_fleet_date":
            replicates.append(_mean([_mean(by_date[item]) for item in sampled]))
        else:
            replicates.append(
                _mean([value for item in sampled for value in by_date[item]])
            )
    alpha = (1.0 - confidence) / 2.0
    if weighting == "equal_fleet_date":
        point = _mean([_mean(by_date[item]) for item in dates])
    else:
        point = _mean([value for item in dates for value in by_date[item]])
    return {
        "point_estimate": point,
        "lower": _quantile(replicates, alpha),
        "upper": _quantile(replicates, 1.0 - alpha),
        "confidence": confidence,
        "iterations": iterations,
        "seed": seed,
        "cluster_unit": "fleet_target_date",
        "weighting": weighting,
        "fleet_dates": len(dates),
        "market_days": len(rows),
    }


def _row_exclusion_reason(row: Mapping[str, Any]) -> str | None:
    if not row["countable"]:
        return f"non_countable_label:{row['label_quality']}"
    if row["label_quality"] not in COUNTABLE_LABEL_QUALITIES:
        return f"non_countable_label:{row['label_quality']}"
    if row["source_quality"] not in COUNTABLE_SOURCE_QUALITIES:
        return f"source_quality:{row['source_quality']}"
    if (
        row["claim_lane"] in LANES_REQUIRING_PARITY
        and row["replay_serve_parity"] != "pass"
    ):
        return f"replay_serve_parity:{row['replay_serve_parity']}"
    if row["prediction_probability"] is None or row["label"] is None:
        return "missing_score_fields"
    return None


class StreamingPointInTimeEvaluator:
    """Aggregate raw rows into one retained market-day and compact summaries."""

    def __init__(
        self,
        *,
        locked_dates: Iterable[str],
        simplex_tolerance: float = 1e-6,
    ) -> None:
        self.locked_dates = frozenset(str(item) for item in locked_dates)
        if not self.locked_dates:
            raise ValueError("locked_dates cannot be empty")
        self.simplex_tolerance = simplex_tolerance
        self.total_rows = 0
        self.window_rows = 0
        self.outside_window_rows = 0
        self.contract_errors: Counter[str] = Counter()
        self.excluded_rows: Counter[str] = Counter()
        self.excluded_cutoffs: Counter[str] = Counter()
        self.excluded_by_date: dict[str, Counter[str]] = defaultdict(Counter)
        self.label_qualities: Counter[str] = Counter()
        self.source_qualities: Counter[str] = Counter()
        self.source_modes: Counter[str] = Counter()
        self.runtime_identities: set[str] = set()
        self.claim_lanes: Counter[str] = Counter()
        self.market_day_metrics: list[MarketDayMetric] = []
        self._current_market_day: tuple[str, str] | None = None
        self._closed_market_days: set[tuple[str, str]] = set()
        self._cutoffs: dict[tuple[str, str, str, str], _CutoffAccumulator] = {}
        self._invalid_cutoff_reasons: dict[tuple[str, str, str, str, str], str] = {}
        self._last_key: tuple[str, ...] | None = None

    def _record_exclusion(self, target_date: str, reason: str) -> None:
        self.excluded_rows[reason] += 1
        self.excluded_by_date[target_date][reason] += 1

    @staticmethod
    def _cutoff_signature(
        row: Mapping[str, Any],
    ) -> tuple[str, str, str, str, str] | None:
        values = (
            _first(row, "target_date", "local_date"),
            _first(row, "market_id", "location_id"),
            _first(row, "cutoff_or_snapshot", "snapshot_id", "cutoff", "captured_at_utc"),
            _first(row, "variant_id", "model_variant_id", "model_version"),
            _first(row, "release_id"),
        )
        if any(value is None or not str(value).strip() for value in values):
            return None
        return (
            str(values[0]).strip(),
            str(values[1]).strip(),
            str(values[2]).strip(),
            str(values[3]).strip(),
            str(values[4]).strip(),
        )

    def _invalidate_cutoff(self, row: Mapping[str, Any], reason: str) -> None:
        signature = self._cutoff_signature(row)
        if signature is not None:
            self._invalid_cutoff_reasons.setdefault(signature, reason)

    def _advance_market_day(self, market_day: tuple[str, str]) -> None:
        if self._current_market_day == market_day:
            return
        self._flush_market_day()
        if market_day in self._closed_market_days:
            raise ContractViolation(
                "noncontiguous_market_day", "market-day rows must be contiguous"
            )
        self._current_market_day = market_day

    def add(self, raw_row: Mapping[str, Any]) -> None:
        self.total_rows += 1
        raw_target = str(_first(raw_row, "target_date", "local_date") or "")
        raw_market = str(_first(raw_row, "market_id", "location_id") or "")
        if raw_target in self.locked_dates and raw_market:
            self._advance_market_day((raw_target, raw_market))
        try:
            row = validate_canonical_row(raw_row)
        except ContractViolation as exc:
            self.contract_errors[exc.code] += 1
            target = str(raw_row.get("target_date") or "unknown")
            self.excluded_by_date[target][f"contract:{exc.code}"] += 1
            self._invalidate_cutoff(raw_row, f"contract:{exc.code}")
            return

        target_date = row["target_date"]
        if target_date not in self.locked_dates:
            self.outside_window_rows += 1
            return
        self.window_rows += 1

        full_key = point_in_time_key(row)
        if self._last_key is not None:
            if full_key == self._last_key:
                self.contract_errors["duplicate_point_in_time_key"] += 1
                self.excluded_by_date[target_date]["contract:duplicate_point_in_time_key"] += 1
                self._invalidate_cutoff(row, "contract:duplicate_point_in_time_key")
                return
            if full_key < self._last_key:
                raise ContractViolation(
                    "unsorted_analytical_input",
                    "streaming input must be sorted by the canonical row key",
                )
        self._last_key = full_key

        market_day = (target_date, row["market_id"])
        self._advance_market_day(market_day)

        self.label_qualities[row["label_quality"]] += 1
        self.source_qualities[row["source_quality"]] += 1
        self.claim_lanes[row["claim_lane"]] += 1
        self.runtime_identities.add(row["runtime_identity"])
        provenance = json.loads(row["source_provenance_json"])
        self.source_modes[str(provenance.get("source_mode") or "unknown")] += 1

        reason = _row_exclusion_reason(row)
        if reason:
            self._record_exclusion(target_date, reason)
            self._invalidate_cutoff(row, reason)
            return
        cutoff_key = (
            row["claim_lane"],
            row["variant_id"],
            row["release_id"],
            row["cutoff_or_snapshot"],
        )
        accumulator = self._cutoffs.setdefault(
            cutoff_key, _CutoffAccumulator.create(row)
        )
        try:
            accumulator.add(row)
        except ContractViolation as exc:
            self.contract_errors[exc.code] += 1
            self.excluded_by_date[target_date][f"contract:{exc.code}"] += 1
            self._invalidate_cutoff(row, f"contract:{exc.code}")

    def _flush_market_day(self) -> None:
        if self._current_market_day is None:
            return
        target_date, market_id = self._current_market_day
        grouped: dict[
            tuple[str, str, str], list[tuple[float, float, int, str]]
        ] = defaultdict(list)
        for cutoff in self._cutoffs.values():
            signature = (
                target_date,
                market_id,
                cutoff.cutoff_or_snapshot,
                cutoff.variant_id,
                cutoff.release_id,
            )
            invalid_reason = self._invalid_cutoff_reasons.get(signature)
            if invalid_reason:
                reason = f"invalid_cutoff:{invalid_reason}"
                self.excluded_cutoffs[reason] += 1
                self.excluded_by_date[target_date][reason] += 1
                continue
            if len(cutoff.runtime_identities) != 1:
                reason = "mixed_runtime_identity_within_cutoff"
                self.excluded_cutoffs[reason] += 1
                self.excluded_by_date[target_date][reason] += 1
                continue
            if abs(sum(cutoff.probabilities) - 1.0) > self.simplex_tolerance:
                reason = "probability_simplex_failure"
                self.excluded_cutoffs[reason] += 1
                self.excluded_by_date[target_date][reason] += 1
                continue
            if abs(sum(cutoff.labels) - 1.0) > self.simplex_tolerance:
                reason = "label_exactly_one_failure"
                self.excluded_cutoffs[reason] += 1
                self.excluded_by_date[target_date][reason] += 1
                continue
            brier = sum(
                (probability - label) ** 2
                for probability, label in zip(
                    cutoff.probabilities, cutoff.labels, strict=True
                )
            )
            log_loss = -sum(
                label * math.log(min(1.0 - 1e-15, max(1e-15, probability)))
                for probability, label in zip(
                    cutoff.probabilities, cutoff.labels, strict=True
                )
            )
            group_key = (
                cutoff.claim_lane,
                cutoff.variant_id,
                cutoff.release_id,
            )
            grouped[group_key].append(
                (
                    brier,
                    log_loss,
                    len(cutoff.probabilities),
                    next(iter(cutoff.runtime_identities)),
                )
            )

        for (lane, variant, release), cutoffs in grouped.items():
            runtime_ids = {item[3] for item in cutoffs}
            if len(runtime_ids) != 1:
                reason = "mixed_runtime_identity_within_market_day"
                self.excluded_cutoffs[reason] += len(cutoffs)
                self.excluded_by_date[target_date][reason] += len(cutoffs)
                continue
            self.market_day_metrics.append(
                MarketDayMetric(
                    target_date=target_date,
                    market_id=market_id,
                    claim_lane=lane,
                    variant_id=variant,
                    release_id=release,
                    categorical_brier=_mean([item[0] for item in cutoffs]),
                    categorical_log_loss=_mean([item[1] for item in cutoffs]),
                    cutoff_count=len(cutoffs),
                    row_count=sum(item[2] for item in cutoffs),
                    runtime_identity=next(iter(runtime_ids)),
                )
            )
        self._closed_market_days.add(self._current_market_day)
        for signature in list(self._invalid_cutoff_reasons):
            if signature[:2] == self._current_market_day:
                del self._invalid_cutoff_reasons[signature]
        self._cutoffs = {}

    def finish(
        self,
        *,
        bootstrap_iterations: int = 2_000,
        bootstrap_seed: int = 31_415,
        generated_at_utc: str | None = None,
        window_lock: Mapping[str, Any] | None = None,
        evaluation_started_at_utc: str | None = None,
        candidate_id: str | None = None,
        release_id: str | None = None,
        validation_plan_hash: str | None = None,
        materialization_manifest_hash: str | None = None,
    ) -> dict[str, Any]:
        self._flush_market_day()
        grouped: dict[tuple[str, str, str], list[MarketDayMetric]] = defaultdict(list)
        for metric in self.market_day_metrics:
            grouped[(metric.claim_lane, metric.variant_id, metric.release_id)].append(metric)

        lanes: dict[str, list[dict[str, Any]]] = {lane: [] for lane in CLAIM_LANES}
        for (lane, variant, release), rows in sorted(grouped.items()):
            metric_payload: dict[str, Any] = {}
            for metric_name in ("categorical_brier", "categorical_log_loss"):
                metric_payload[metric_name] = {
                    "equal_market_day": date_clustered_bootstrap_interval(
                        rows,
                        metric=metric_name,
                        iterations=bootstrap_iterations,
                        seed=bootstrap_seed,
                        weighting="equal_market_day",
                    ),
                    "equal_fleet_date": date_clustered_bootstrap_interval(
                        rows,
                        metric=metric_name,
                        iterations=bootstrap_iterations,
                        seed=bootstrap_seed,
                        weighting="equal_fleet_date",
                    ),
                }
            lanes[lane].append(
                {
                    "variant_id": variant,
                    "release_id": release,
                    "market_days": len(rows),
                    "fleet_dates": len({row.target_date for row in rows}),
                    "markets": sorted({row.market_id for row in rows}),
                    "runtime_identities": sorted({row.runtime_identity for row in rows}),
                    "cutoffs": sum(row.cutoff_count for row in rows),
                    "scored_rows": sum(row.row_count for row in rows),
                    "metrics": metric_payload,
                    "market_day_rows": [asdict(row) for row in rows],
                }
            )

        stale_failed = sum(
            count
            for quality, count in self.source_qualities.items()
            if quality in {"stale", "failed"}
        )
        quality_denominator = sum(self.source_qualities.values())
        stale_failed_rate = stale_failed / quality_denominator if quality_denominator else None
        source_quality_pass = (
            stale_failed_rate is not None and stale_failed_rate < 0.05
        )
        blocking = bool(
            self.contract_errors or self.excluded_cutoffs or not source_quality_pass
        )
        if not self.market_day_metrics:
            blocking = True
        generated = _generated_at_utc(generated_at_utc)
        started = _generated_at_utc(evaluation_started_at_utc or generated)
        payload = {
            "schema_version": EVALUATION_SCHEMA_VERSION,
            "artifact_type": "point_in_time_streaming_evaluation",
            "generated_at_utc": generated,
            "evaluation_started_at_utc": started,
            "status": "BLOCK" if blocking else "PASS",
            "independent_evidence_unit": "fleet_date_and_market_day",
            "row_multiplier_counts_as_independent_evidence": False,
            "lane_isolation": {
                "status": "PASS",
                "lanes": list(CLAIM_LANES),
                "cross_lane_pooling": False,
            },
            "window_lock": dict(window_lock or {"target_dates": sorted(self.locked_dates)}),
            "counts": {
                "input_rows": self.total_rows,
                "window_rows": self.window_rows,
                "outside_window_rows": self.outside_window_rows,
                "market_day_summaries": len(self.market_day_metrics),
                "market_days": len(
                    {(row.target_date, row.market_id) for row in self.market_day_metrics}
                ),
                "fleet_dates": len({row.target_date for row in self.market_day_metrics}),
                "excluded_rows": sum(self.excluded_rows.values()),
                "excluded_cutoffs": sum(self.excluded_cutoffs.values()),
            },
            "selected_labels": dict(sorted(self.label_qualities.items())),
            "excluded_rows_by_reason": dict(sorted(self.excluded_rows.items())),
            "excluded_cutoffs_by_reason": dict(sorted(self.excluded_cutoffs.items())),
            "contract_errors": dict(sorted(self.contract_errors.items())),
            "excluded_target_dates": {
                target: dict(sorted(reasons.items()))
                for target, reasons in sorted(self.excluded_by_date.items())
            },
            "source_quality": {
                "counts": dict(sorted(self.source_qualities.items())),
                "stale_or_failed_rate": stale_failed_rate,
                "target_max_rate": 0.05,
                "target_status": (
                    "PASS" if source_quality_pass else "BLOCK"
                ),
            },
            "source_modes": dict(sorted(self.source_modes.items())),
            "runtime_identities": sorted(self.runtime_identities),
            "claim_lane_rows": dict(sorted(self.claim_lanes.items())),
            "streaming_memory_contract": {
                "raw_rows_retained_after_market_day_flush": 0,
                "active_market_days": 1,
                "retained_objects": "market-day summaries and fleet-date clusters only",
            },
            "metric_definition": {
                "categorical_brier": "sum over bands per cutoff, then equal-cutoff market-day mean",
                "categorical_log_loss": "winning-band log loss per cutoff, then equal-cutoff market-day mean",
                "confidence_interval": "deterministic whole-fleet-date clustered percentile bootstrap",
            },
            "lanes": lanes,
        }
        normalized_candidate = _optional_identity(candidate_id, "candidate_id")
        normalized_release = _optional_identity(release_id, "release_id")
        if normalized_candidate is not None:
            payload["candidate_id"] = normalized_candidate
        if normalized_release is not None:
            payload["release_id"] = normalized_release
        if validation_plan_hash is not None or materialization_manifest_hash is not None:
            payload["contract_binding"] = {
                "validation_plan_hash": str(validation_plan_hash or ""),
                "materialization_manifest_hash": str(materialization_manifest_hash or ""),
            }
        return _finalize_hash(payload, "evaluation_hash")


def evaluate_point_in_time_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    locked_dates: Iterable[str],
    simplex_tolerance: float = 1e-6,
    bootstrap_iterations: int = 2_000,
    bootstrap_seed: int = 31_415,
    generated_at_utc: str | None = None,
    window_lock: Mapping[str, Any] | None = None,
    evaluation_started_at_utc: str | None = None,
    candidate_id: str | None = None,
    release_id: str | None = None,
    validation_plan_hash: str | None = None,
    materialization_manifest_hash: str | None = None,
) -> dict[str, Any]:
    started = _generated_at_utc(evaluation_started_at_utc or generated_at_utc)
    evaluator = StreamingPointInTimeEvaluator(
        locked_dates=locked_dates,
        simplex_tolerance=simplex_tolerance,
    )
    for row in rows:
        evaluator.add(row)
    return evaluator.finish(
        bootstrap_iterations=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
        generated_at_utc=generated_at_utc,
        window_lock=window_lock,
        evaluation_started_at_utc=started,
        candidate_id=candidate_id,
        release_id=release_id,
        validation_plan_hash=validation_plan_hash,
        materialization_manifest_hash=materialization_manifest_hash,
    )


def collect_parquet_fleet_dates(
    path: str | Path, *, batch_rows: int = 65_536
) -> tuple[str, ...]:
    """Scan only the date column; no prediction rows are retained."""

    dates: set[str] = set()
    parquet = pq.ParquetFile(path)
    if "target_date" not in parquet.schema_arrow.names:
        raise ContractViolation("missing_target_date", "Parquet target_date column missing")
    for batch in parquet.iter_batches(batch_size=batch_rows, columns=["target_date"]):
        dates.update(str(value) for value in batch.column(0).to_pylist() if value)
    for value in dates:
        _parse_date(value)
    return tuple(sorted(dates))


def collect_jsonl_fleet_dates(
    path: str | Path, *, max_line_bytes: int = 4 * 1024 * 1024
) -> tuple[str, ...]:
    dates = {
        _required_text(row.get("target_date"), "missing_target_date", "target_date")
        for row in iter_point_in_time_jsonl(path, max_line_bytes=max_line_bytes)
    }
    for value in dates:
        _parse_date(value)
    return tuple(sorted(dates))


def build_window_lock(
    available_dates: Iterable[str | date],
    *,
    input_sha256: str,
    window_days: int = 14,
    window_end: str | date | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Lock a calendar window before any candidate metric is evaluated."""

    dates = _unique_dates(available_dates)
    if not dates:
        raise ValueError("cannot lock an empty evaluation corpus")
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    end = (
        window_end
        if isinstance(window_end, date)
        else _parse_date(window_end, "window_end")
        if window_end
        else dates[-1]
    )
    start = end - timedelta(days=window_days - 1)
    selected = [item for item in dates if start <= item <= end]
    expected = [start + timedelta(days=offset) for offset in range(window_days)]
    missing = [item for item in expected if item not in set(selected)]
    lock_basis = {
        "input_sha256": input_sha256,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "window_days": window_days,
        "target_dates": [item.isoformat() for item in selected],
    }
    return {
        **lock_basis,
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "generated_at_utc": _generated_at_utc(generated_at_utc),
        "status": "PASS" if not missing and selected else "BLOCK",
        "window_lock_id": sha256_text(canonical_json(lock_basis)),
        "missing_calendar_dates": [item.isoformat() for item in missing],
        "candidate_selection_permission": "forbidden",
        "locked_before_scoring": True,
    }


def evaluate_point_in_time_parquet(
    parquet_path: str | Path,
    *,
    manifest_path: str | Path,
    window_days: int = 14,
    window_end: str | date | None = None,
    batch_rows: int = 65_536,
    bootstrap_iterations: int = 2_000,
    bootstrap_seed: int = 31_415,
    generated_at_utc: str | None = None,
    evaluation_started_at_utc: str | None = None,
    candidate_id: str | None = None,
    release_id: str | None = None,
    validation_plan_hash: str | None = None,
) -> dict[str, Any]:
    manifest = verify_materialization_manifest(
        parquet_path,
        manifest_path,
        expected_candidate_id=candidate_id,
        expected_release_id=release_id,
    )
    dates = collect_parquet_fleet_dates(parquet_path, batch_rows=batch_rows)
    lock = build_window_lock(
        dates,
        input_sha256=str((manifest.get("derived_artifact") or {}).get("sha256") or ""),
        window_days=window_days,
        window_end=window_end,
        generated_at_utc=generated_at_utc,
    )
    started = _generated_at_utc(evaluation_started_at_utc or generated_at_utc)
    payload = evaluate_point_in_time_rows(
        iter_point_in_time_parquet(parquet_path, batch_rows=batch_rows),
        locked_dates=lock["target_dates"],
        bootstrap_iterations=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
        generated_at_utc=generated_at_utc,
        window_lock=lock,
        evaluation_started_at_utc=started,
        candidate_id=candidate_id,
        release_id=release_id,
        validation_plan_hash=validation_plan_hash,
        materialization_manifest_hash=str(manifest.get("manifest_hash") or ""),
    )
    payload.pop("evaluation_hash", None)
    payload["input"] = {
        "path": str(parquet_path),
        "sha256": lock["input_sha256"],
        "materialization_manifest": str(manifest_path),
        "materialization_manifest_hash": str(manifest.get("manifest_hash") or ""),
        "source_modes": (manifest.get("counts") or {}).get("source_modes") or {},
    }
    if lock["status"] != "PASS":
        payload["status"] = "BLOCK"
    return _finalize_hash(payload, "evaluation_hash")


def verify_streaming_evaluation_payload(
    payload: Mapping[str, Any],
    *,
    expected_candidate_id: str | None = None,
    expected_release_id: str | None = None,
    expected_corpus_sha256: str | None = None,
    expected_manifest_hash: str | None = None,
    expected_validation_plan_hash: str | None = None,
    require_production_window: bool = False,
    now_utc: datetime | None = None,
    max_age_days: int | None = None,
) -> dict[str, Any]:
    """Validate the streamed result, locked window, lanes, and clustered intervals."""

    if payload.get("schema_version") != EVALUATION_SCHEMA_VERSION:
        raise ContractViolation("invalid_streaming_evaluation", "schema mismatch")
    if payload.get("artifact_type") != "point_in_time_streaming_evaluation":
        raise ContractViolation("invalid_streaming_evaluation", "artifact type mismatch")
    _verify_self_hash(payload, "evaluation_hash", "streaming_evaluation_hash_mismatch")
    if payload.get("status") != "PASS":
        raise ContractViolation("streaming_evaluation_not_pass", "evaluation is not PASS")
    generated = _parse_utc(payload.get("generated_at_utc"), "evaluation.generated_at_utc")
    started = _parse_utc(
        payload.get("evaluation_started_at_utc"), "evaluation.evaluation_started_at_utc"
    )
    if started > generated:
        raise ContractViolation(
            "evaluation_time_order_invalid", "evaluation start is after evaluation completion"
        )
    if max_age_days is not None:
        if max_age_days <= 0:
            raise ValueError("max_age_days must be positive")
        now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if generated > now + timedelta(minutes=5):
            raise ContractViolation("streaming_evaluation_from_future", "evaluation is in the future")
        if now - generated > timedelta(days=max_age_days):
            raise ContractViolation("stale_streaming_evaluation", "evaluation is stale")
    if expected_candidate_id is not None and payload.get("candidate_id") != expected_candidate_id:
        raise ContractViolation("streaming_evaluation_identity_mismatch", "candidate identity mismatch")
    if expected_release_id is not None and payload.get("release_id") != expected_release_id:
        raise ContractViolation("streaming_evaluation_identity_mismatch", "release identity mismatch")

    input_row = payload.get("input")
    if expected_corpus_sha256 is not None:
        if not isinstance(input_row, Mapping) or input_row.get("sha256") != expected_corpus_sha256:
            raise ContractViolation("streaming_evaluation_corpus_mismatch", "corpus hash mismatch")
    binding = payload.get("contract_binding")
    if expected_manifest_hash is not None or expected_validation_plan_hash is not None:
        if not isinstance(binding, Mapping):
            raise ContractViolation("streaming_evaluation_contract_mismatch", "contract binding missing")
        if binding.get("materialization_manifest_hash") != expected_manifest_hash:
            raise ContractViolation("streaming_evaluation_contract_mismatch", "manifest hash mismatch")
        if binding.get("validation_plan_hash") != expected_validation_plan_hash:
            raise ContractViolation("streaming_evaluation_contract_mismatch", "plan hash mismatch")
        if not isinstance(input_row, Mapping) or input_row.get(
            "materialization_manifest_hash"
        ) != expected_manifest_hash:
            raise ContractViolation("streaming_evaluation_contract_mismatch", "input manifest mismatch")

    lock = payload.get("window_lock")
    if not isinstance(lock, Mapping):
        raise ContractViolation("invalid_evaluation_window_lock", "window lock is missing")
    lock_basis = {
        "input_sha256": lock.get("input_sha256"),
        "window_start": lock.get("window_start"),
        "window_end": lock.get("window_end"),
        "window_days": lock.get("window_days"),
        "target_dates": lock.get("target_dates"),
    }
    if lock.get("window_lock_id") != sha256_text(canonical_json(lock_basis)):
        raise ContractViolation("invalid_evaluation_window_lock", "window lock hash mismatch")
    lock_generated = _parse_utc(lock.get("generated_at_utc"), "window_lock.generated_at_utc")
    if lock_generated > started:
        raise ContractViolation(
            "window_selected_after_evaluation",
            "evaluation window was selected after scoring began",
        )
    target_dates = tuple(str(value) for value in lock.get("target_dates") or ())
    for value in target_dates:
        _parse_date(value, "window_lock.target_date")
    if expected_corpus_sha256 is not None and lock.get("input_sha256") != expected_corpus_sha256:
        raise ContractViolation("invalid_evaluation_window_lock", "window corpus hash mismatch")
    if require_production_window:
        if (
            lock.get("schema_version") != EVALUATION_SCHEMA_VERSION
            or lock.get("status") != "PASS"
            or lock.get("window_days") != 14
            or len(target_dates) != 14
            or len(set(target_dates)) != 14
            or lock.get("missing_calendar_dates") != []
            or lock.get("candidate_selection_permission") != "forbidden"
            or lock.get("locked_before_scoring") is not True
        ):
            raise ContractViolation(
                "invalid_evaluation_window_lock", "production window lock is incomplete"
            )
        parsed_dates = [_parse_date(value, "window_lock.target_date") for value in target_dates]
        expected_dates = [parsed_dates[0] + timedelta(days=offset) for offset in range(14)]
        if parsed_dates != expected_dates:
            raise ContractViolation(
                "invalid_evaluation_window_lock", "production window is not contiguous"
            )
        if lock.get("window_start") != target_dates[0] or lock.get("window_end") != target_dates[-1]:
            raise ContractViolation(
                "invalid_evaluation_window_lock", "production window bounds are inconsistent"
            )

    lane_isolation = payload.get("lane_isolation")
    if lane_isolation != {
        "status": "PASS",
        "lanes": list(CLAIM_LANES),
        "cross_lane_pooling": False,
    }:
        raise ContractViolation("invalid_lane_isolation", "claim lanes are not isolated")
    lanes = payload.get("lanes")
    if not isinstance(lanes, Mapping) or set(lanes) != set(CLAIM_LANES):
        raise ContractViolation("invalid_lane_isolation", "claim lane inventory is incomplete")
    for lane, summaries in lanes.items():
        if not isinstance(summaries, list):
            raise ContractViolation("invalid_streaming_evaluation", f"lane {lane} is malformed")
        for summary in summaries:
            metrics = summary.get("metrics") if isinstance(summary, Mapping) else None
            if not isinstance(metrics, Mapping):
                raise ContractViolation("invalid_clustered_intervals", "metric summary is missing")
            for metric_name in ("categorical_brier", "categorical_log_loss"):
                metric = metrics.get(metric_name)
                if not isinstance(metric, Mapping) or set(metric) != {
                    "equal_market_day",
                    "equal_fleet_date",
                }:
                    raise ContractViolation(
                        "invalid_clustered_intervals", "weighting interval inventory is incomplete"
                    )
                for weighting, interval in metric.items():
                    if (
                        not isinstance(interval, Mapping)
                        or interval.get("cluster_unit") != "fleet_target_date"
                        or interval.get("weighting") != weighting
                        or int(interval.get("fleet_dates") or 0) <= 0
                        or int(interval.get("market_days") or 0) <= 0
                    ):
                        raise ContractViolation(
                            "invalid_clustered_intervals", "interval is not date-clustered"
                        )
    if require_production_window:
        weather_summaries = lanes.get("weather_only") or []
        if not weather_summaries or any(
            summary.get("release_id") != expected_release_id
            or int(summary.get("fleet_dates") or 0) != 14
            for summary in weather_summaries
        ):
            raise ContractViolation(
                "candidate_evaluation_missing", "candidate has no complete weather-only window"
            )
    return dict(payload)


def _read_contract_json(path: str | Path, *, code: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractViolation(code, f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractViolation(code, f"{path} must contain a JSON object")
    return payload


def verify_production_point_in_time_artifacts(
    *,
    corpus_path: str | Path,
    materialization_manifest_path: str | Path,
    validation_plan_path: str | Path,
    streaming_evaluation_path: str | Path,
    expected_candidate_id: str,
    expected_release_id: str,
    now_utc: datetime | None = None,
    max_age_days: int | None = None,
) -> dict[str, Any]:
    """Verify one canonical, hash-linked production qualification evidence graph."""

    corpus_path = Path(corpus_path)
    manifest = verify_materialization_manifest(
        corpus_path,
        materialization_manifest_path,
        expected_candidate_id=expected_candidate_id,
        expected_release_id=expected_release_id,
    )
    corpus_sha = sha256_file(corpus_path)
    manifest_hash = str(manifest.get("manifest_hash") or "")
    fleet_dates = collect_parquet_fleet_dates(corpus_path)
    plan = _read_contract_json(validation_plan_path, code="invalid_validation_plan")
    verify_validation_plan_payload(
        plan,
        expected_candidate_id=expected_candidate_id,
        expected_release_id=expected_release_id,
        expected_corpus_sha256=corpus_sha,
        expected_manifest_hash=manifest_hash,
        expected_fleet_dates=fleet_dates,
        require_fit_receipts=True,
    )
    evaluation = _read_contract_json(
        streaming_evaluation_path, code="invalid_streaming_evaluation"
    )
    verify_streaming_evaluation_payload(
        evaluation,
        expected_candidate_id=expected_candidate_id,
        expected_release_id=expected_release_id,
        expected_corpus_sha256=corpus_sha,
        expected_manifest_hash=manifest_hash,
        expected_validation_plan_hash=str(plan.get("plan_hash") or ""),
        require_production_window=True,
        now_utc=now_utc,
        max_age_days=max_age_days,
    )
    plan_generated = _parse_utc(
        plan.get("generated_at_utc"), "validation_plan.generated_at_utc"
    )
    evaluation_started = _parse_utc(
        evaluation.get("evaluation_started_at_utc"),
        "evaluation.evaluation_started_at_utc",
    )
    if plan_generated > evaluation_started:
        raise ContractViolation(
            "plan_selected_after_evaluation", "validation plan was selected after scoring began"
        )
    locked_dates = set((evaluation.get("window_lock") or {}).get("target_dates") or ())
    if not locked_dates <= set(fleet_dates):
        raise ContractViolation(
            "streaming_evaluation_corpus_mismatch", "locked dates escape the frozen corpus"
        )
    return {
        "status": "PASS",
        "candidate_id": expected_candidate_id,
        "release_id": expected_release_id,
        "corpus_sha256": corpus_sha,
        "materialization_manifest_hash": manifest_hash,
        "validation_plan_hash": plan["plan_hash"],
        "streaming_evaluation_hash": evaluation["evaluation_hash"],
        "fleet_dates": len(fleet_dates),
        "locked_window_days": len(locked_dates),
        "fit_receipt_count": len(plan.get("fit_receipts") or ()),
    }


def _read_dates_file(path: str | Path) -> list[str]:
    text = Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return [line.strip() for line in text.splitlines() if line.strip()]
    if isinstance(payload, list):
        return [str(item) for item in payload]
    if isinstance(payload, dict):
        values = payload.get("fleet_dates") or payload.get("target_dates") or []
        return [str(item) for item in values]
    raise ValueError("dates file must contain a JSON list/object or one date per line")


def _cmd_materialize(args: argparse.Namespace) -> None:
    folders = [Path(item) for item in args.folder]
    if not folders:
        folders = discover_settled_folders(
            root=args.snapshots_root,
            as_of=args.as_of or None,
            required_file=args.required_file,
            market_id=args.market_id or None,
        )
    payload = materialize_point_in_time_table(
        folders,
        parquet_out=args.out,
        manifest_out=args.manifest_out,
        artifact_family=args.artifact_family,
        snapshots_root=args.snapshots_root,
        archive_root=args.archive_root,
        archive_as_of_date=args.as_of or None,
        prefer_archive=not args.text_only,
        explicit_claim_lane=args.claim_lane or None,
        max_market_days=args.max_market_days,
        max_rows_per_market_day=args.max_rows_per_market_day,
    )
    print(
        "point-in-time materialization: "
        f"status={payload['status']} rows={payload['counts']['accepted_rows']} "
        f"excluded={payload['counts']['excluded_rows']}"
    )
    if payload["status"] != "PASS":
        raise SystemExit(1)


def _cmd_folds(args: argparse.Namespace) -> None:
    dates = list(args.date)
    if args.dates_file:
        dates.extend(_read_dates_file(args.dates_file))
    if not dates:
        raise SystemExit("at least one --date or --dates-file is required")
    payload = validation_plan_payload(
        dates,
        outer_min_train_dates=args.outer_min_train_dates,
        inner_min_train_dates=args.inner_min_train_dates,
        outer_validation_dates=args.outer_validation_dates,
        inner_validation_dates=args.inner_validation_dates,
        embargo_days=args.embargo_days,
        step_dates=args.step_dates,
    )
    _atomic_write_json(args.out, payload)
    print(f"point-in-time folds: status={payload['status']} outer={len(payload['folds'])}")
    if payload["status"] != "PASS":
        raise SystemExit(1)


def _cmd_evaluate(args: argparse.Namespace) -> None:
    payload = evaluate_point_in_time_parquet(
        args.input,
        manifest_path=args.manifest,
        window_days=args.window_days,
        window_end=args.window_end or None,
        batch_rows=args.batch_rows,
        bootstrap_iterations=args.bootstrap_iterations,
        bootstrap_seed=args.bootstrap_seed,
    )
    _atomic_write_json(args.out, payload)
    print(
        "point-in-time evaluation: "
        f"status={payload['status']} market_days={payload['counts']['market_days']} "
        f"fleet_dates={payload['counts']['fleet_dates']}"
    )
    if payload["status"] != "PASS":
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bounded point-in-time materialization, validation folds, and evaluation."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    materialize = subparsers.add_parser(
        "materialize", help="write a derived canonical Parquet table"
    )
    materialize.add_argument("--folder", action="append", default=[])
    materialize.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    materialize.add_argument("--archive-root", default=str(DEFAULT_ARCHIVE_ROOT))
    materialize.add_argument("--as-of", default="")
    materialize.add_argument("--market-id", default="")
    materialize.add_argument("--artifact-family", default="snapshots_long")
    materialize.add_argument("--required-file", default="snapshots_long.csv")
    materialize.add_argument("--claim-lane", choices=CLAIM_LANES, default="")
    materialize.add_argument("--text-only", action="store_true")
    materialize.add_argument("--max-market-days", type=int, default=500)
    materialize.add_argument("--max-rows-per-market-day", type=int, default=250_000)
    materialize.add_argument("--out", default=str(DEFAULT_PARQUET_OUT))
    materialize.add_argument("--manifest-out", default=str(DEFAULT_MANIFEST_OUT))
    materialize.set_defaults(func=_cmd_materialize)

    folds = subparsers.add_parser(
        "folds", help="write nested fleet-date rolling-origin folds"
    )
    folds.add_argument("--date", action="append", default=[])
    folds.add_argument("--dates-file", default="")
    folds.add_argument("--outer-min-train-dates", type=int, default=14)
    folds.add_argument("--inner-min-train-dates", type=int, default=7)
    folds.add_argument("--outer-validation-dates", type=int, default=1)
    folds.add_argument("--inner-validation-dates", type=int, default=1)
    folds.add_argument("--embargo-days", type=int, choices=range(3, 8), default=3)
    folds.add_argument("--step-dates", type=int, default=1)
    folds.add_argument("--out", default=str(DEFAULT_FOLDS_OUT))
    folds.set_defaults(func=_cmd_folds)

    evaluate = subparsers.add_parser(
        "evaluate", help="stream a locked calendar window into market-day metrics"
    )
    evaluate.add_argument("--input", default=str(DEFAULT_PARQUET_OUT))
    evaluate.add_argument("--manifest", default=str(DEFAULT_MANIFEST_OUT))
    evaluate.add_argument("--window-days", type=int, default=14)
    evaluate.add_argument("--window-end", default="")
    evaluate.add_argument("--batch-rows", type=int, default=65_536)
    evaluate.add_argument("--bootstrap-iterations", type=int, default=2_000)
    evaluate.add_argument("--bootstrap-seed", type=int, default=31_415)
    evaluate.add_argument("--out", default=str(DEFAULT_EVALUATION_OUT))
    evaluate.set_defaults(func=_cmd_evaluate)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
