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
import pickle
import random
import re
import stat
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Protocol, Sequence

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from weather.backtesting.settled_days import discover_settled_folders, folder_market_id
from weather.calibration.pooled_candidate_replay import (
    iter_bounded_preselection_source_market_days,
    iter_bounded_pooled_band_candidate_replay_market_days,
    load_bounded_preselection_folder_inputs,
)
from weather.calibration.pooled_training import (
    verify_pooled_point_in_time_training_evidence,
)
from weather.market.market_config import date_from_event_slug
from weather.operations.closed_market_day_archive import (
    DEFAULT_ARCHIVE_ROOT,
    DEFAULT_SNAPSHOTS_ROOT,
    read_market_day_artifact,
)
from weather.paths import data_path
from weather.reporting.promotion.promotion_corpus import (
    build_promotion_corpus,
    load_manifest as load_promotion_corpus_manifest,
)
from weather.schema_registry import schema_version


CONTRACT_SCHEMA_VERSION = schema_version("point_in_time_analytical_contract")
MATERIALIZER_SCHEMA_VERSION = schema_version("point_in_time_materializer")
VALIDATION_PLAN_SCHEMA_VERSION = schema_version("point_in_time_validation_plan")
FIT_RECEIPT_SCHEMA_VERSION = schema_version("point_in_time_fit_receipt")
EVALUATION_SCHEMA_VERSION = schema_version("point_in_time_streaming_evaluation")
PRODUCTION_PRESELECTION_SCHEMA_VERSION = schema_version(
    "production_point_in_time_preselection"
)
PRODUCTION_PRESELECTION_SOURCE_SCHEMA_VERSION = schema_version(
    "production_point_in_time_preselection_source"
)
CANDIDATE_TRAINING_GRAPH_SCHEMA_VERSION = schema_version(
    "point_in_time_candidate_training_graph"
)
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
FIT_RECEIPT_PAYLOAD_HASH_ALGORITHM = "sha256"
FIT_RECEIPT_PAYLOAD_CANONICALIZATION = "canonical_json"
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

PRODUCTION_PRESELECTION_SOURCE_ARROW_SCHEMA = pa.schema(
    [
        pa.field("schema_version", pa.string(), nullable=False),
        pa.field("target_date", pa.string(), nullable=False),
        pa.field("market_id", pa.string(), nullable=False),
        pa.field("cutoff_or_snapshot", pa.string(), nullable=False),
        pa.field("band", pa.string(), nullable=False),
        pa.field("feature_available_at_utc", pa.string(), nullable=False),
        pa.field("prediction_boundary_at_utc", pa.string(), nullable=False),
        pa.field("label_quality", pa.string(), nullable=False),
        pa.field("countable", pa.bool_(), nullable=False),
        pa.field("claim_lane", pa.string(), nullable=False),
        pa.field("source_quality", pa.string(), nullable=False),
        pa.field("label", pa.float64(), nullable=False),
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
                    "event_manifest_hash": provenance.get("event_manifest_hash"),
                    "release_id": provenance.get("release_id"),
                    "runtime_identity_key": provenance.get("runtime_identity_key"),
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
                if (
                    temp_out.exists()
                    and temp_out.stat().st_size
                    > PRODUCTION_MAX_SOURCE_PARQUET_BYTES
                ):
                    raise BoundedReadError(
                        "production preselection Parquet byte bound exceeded"
                    )
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
    if (
        temp_out.exists()
        and temp_out.stat().st_size > PRODUCTION_MAX_SOURCE_PARQUET_BYTES
    ):
        temp_out.unlink(missing_ok=True)
        raise BoundedReadError(
            "production preselection Parquet byte bound exceeded"
        )

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


def validate_production_preselection_source_row(
    row: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one candidate-independent production population row."""

    if row.get("schema_version") != PRODUCTION_PRESELECTION_SOURCE_SCHEMA_VERSION:
        raise ContractViolation(
            "invalid_preselection_source_schema",
            "unexpected production preselection source row schema",
        )
    normalized = dict(row)
    _parse_date(row.get("target_date"))
    for field in ("target_date", "market_id", "cutoff_or_snapshot", "band"):
        normalized[field] = _required_text(
            row.get(field), f"missing_{field}", field
        )
        if len(normalized[field].encode("utf-8")) > PRODUCTION_MAX_SOURCE_TEXT_BYTES:
            raise ContractViolation(
                "oversized_preselection_source_field",
                f"{field} exceeds the production source text bound",
            )
    feature_time = _parse_utc(
        row.get("feature_available_at_utc"), "feature_available_at_utc"
    )
    boundary_time = _parse_utc(
        row.get("prediction_boundary_at_utc"), "prediction_boundary_at_utc"
    )
    if feature_time > boundary_time:
        raise ContractViolation(
            "feature_available_after_prediction_boundary",
            "feature availability cannot be later than the frozen prediction boundary",
        )
    normalized["feature_available_at_utc"] = feature_time.isoformat()
    normalized["prediction_boundary_at_utc"] = boundary_time.isoformat()
    normalized["label_quality"] = _normalize_label_quality(row.get("label_quality"))
    normalized["countable"] = _strict_bool(row.get("countable"), "countable")
    normalized["claim_lane"] = normalize_claim_lane(row.get("claim_lane"))
    normalized["source_quality"] = _normalize_source_quality(row.get("source_quality"))
    normalized["label"] = _normalized_label(row.get("label"))
    if (
        not normalized["countable"]
        or normalized["label_quality"] not in COUNTABLE_LABEL_QUALITIES
        or normalized["claim_lane"] != "weather_only"
        or normalized["source_quality"] not in COUNTABLE_SOURCE_QUALITIES
        or normalized["label"] is None
    ):
        raise ContractViolation(
            "noncountable_preselection_source_row",
            "production preselection source rows must be countable, healthy, "
            "weather-only rows with complete labels",
        )
    return {
        field.name: normalized.get(field.name)
        for field in PRODUCTION_PRESELECTION_SOURCE_ARROW_SCHEMA
    }


def iter_production_preselection_source_parquet(
    path: str | Path,
    *,
    batch_rows: int = 65_536,
) -> Iterator[dict[str, Any]]:
    """Yield the narrow pre-candidate population projection in bounded batches."""

    if batch_rows <= 0:
        raise ValueError("batch_rows must be positive")
    parquet = pq.ParquetFile(path)
    actual_schema = parquet.schema_arrow
    if not actual_schema.equals(
        PRODUCTION_PRESELECTION_SOURCE_ARROW_SCHEMA,
        check_metadata=False,
    ):
        raise ContractViolation(
            "invalid_preselection_source_columns",
            "production preselection source must use the exact candidate-independent schema",
        )
    for batch in parquet.iter_batches(batch_size=batch_rows):
        for row in batch.to_pylist():
            yield validate_production_preselection_source_row(row)


@contextmanager
def _exclusive_preselection_output_locks(*paths: str | Path):
    """Reserve every final output name against concurrent materializers."""

    locks = sorted(
        {
            Path(path).resolve().with_name(
                f".{Path(path).name}.preselection-publish.lock"
            )
            for path in paths
        },
        key=str,
    )
    opened: list[tuple[Path, int]] = []
    try:
        for lock in locks:
            lock.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError as exc:
                raise FileExistsError(
                    f"concurrent production preselection publication is locked: {lock}"
                ) from exc
            opened.append((lock, fd))
        yield
    finally:
        for lock, fd in reversed(opened):
            try:
                os.close(fd)
            finally:
                lock.unlink(missing_ok=True)


def materialize_production_preselection_source(
    *,
    replay_manifest: str | Path,
    parquet_out: str | Path,
    manifest_out: str | Path,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    max_market_days: int = 60,
    max_rows_per_market_day: int = 250_000,
    batch_rows: int = 65_536,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    with _exclusive_preselection_output_locks(parquet_out, manifest_out):
        return _materialize_production_preselection_source_locked(
            replay_manifest=replay_manifest,
            parquet_out=parquet_out,
            manifest_out=manifest_out,
            snapshots_root=snapshots_root,
            max_market_days=max_market_days,
            max_rows_per_market_day=max_rows_per_market_day,
            batch_rows=batch_rows,
            generated_at_utc=generated_at_utc,
        )


def _materialize_production_preselection_source_locked(
    *,
    replay_manifest: str | Path,
    parquet_out: str | Path,
    manifest_out: str | Path,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    max_market_days: int = 60,
    max_rows_per_market_day: int = 250_000,
    batch_rows: int = 65_536,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Replay a pinned population before training without inventing model identity."""

    if (
        max_market_days <= 0
        or max_market_days > 60
        or max_rows_per_market_day <= 0
        or max_rows_per_market_day > 250_000
        or batch_rows <= 0
        or batch_rows > 65_536
    ):
        raise ValueError("production preselection streaming bounds are invalid")
    parquet_out = Path(parquet_out).resolve()
    manifest_out = Path(manifest_out).resolve()
    if parquet_out == manifest_out:
        raise ValueError("preselection corpus and manifest outputs must be distinct")
    if parquet_out.exists() or manifest_out.exists():
        raise FileExistsError(
            "production preselection source outputs are immutable and already exist"
        )
    replay_manifest = Path(replay_manifest).resolve()
    replay = _load_production_replay_manifest(replay_manifest)
    replay_sha256 = sha256_file(replay_manifest)
    entries = list(replay.get("entries") or ())
    expected_market_day_counts: dict[tuple[str, str], int] = {}
    for entry in entries:
        key = (
            str(entry.get("target_date") or ""),
            str(entry.get("market_id") or ""),
        )
        entry_rows = int(entry.get("row_count") or 0)
        if (
            not all(key)
            or key in expected_market_day_counts
            or not 0 < entry_rows <= max_rows_per_market_day
        ):
            raise BoundedReadError("replay manifest market-day inventory is invalid")
        expected_market_day_counts[key] = entry_rows
    if not entries or len(entries) > max_market_days:
        raise BoundedReadError(
            f"market-day bound exceeded: {len(entries)} > {max_market_days}"
        )

    parquet_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    temp_out = parquet_out.with_name(f".{parquet_out.name}.{os.getpid()}.tmp")
    temp_manifest = manifest_out.with_name(
        f".{manifest_out.name}.{os.getpid()}.tmp"
    )
    if temp_out.exists():
        temp_out.unlink()
    if temp_manifest.exists():
        temp_manifest.unlink()
    writer: pq.ParquetWriter | None = None
    row_count = 0
    market_days = 0
    observed_market_day_counts: Counter[tuple[str, str]] = Counter()
    previous_coordinate: tuple[str, str, str, str] | None = None
    try:
        for day_rows in iter_bounded_preselection_source_market_days(
            corpus_manifest_path=replay_manifest,
            expected_manifest_sha256=replay_sha256,
            snapshots_root=snapshots_root,
            max_market_days=max_market_days,
            max_rows_per_market_day=max_rows_per_market_day,
        ):
            if not day_rows or len(day_rows) > max_rows_per_market_day:
                raise BoundedReadError("preselection replay produced an invalid market-day")
            day_market_days = {
                (str(row.get("target_date") or ""), str(row.get("market_id") or ""))
                for row in day_rows
            }
            if len(day_market_days) != 1:
                raise ContractViolation(
                    "preselection_source_market_day_mismatch",
                    "one replay batch must contain exactly one market-day",
                )
            day_market_day = next(iter(day_market_days))
            for index, raw_row in enumerate(day_rows):
                canonical = validate_production_preselection_source_row(
                    {
                        "schema_version": PRODUCTION_PRESELECTION_SOURCE_SCHEMA_VERSION,
                        **raw_row,
                    }
                )
                coordinate = (
                    canonical["target_date"],
                    canonical["market_id"],
                    canonical["cutoff_or_snapshot"],
                    canonical["band"],
                )
                if previous_coordinate is not None and coordinate <= previous_coordinate:
                    raise ContractViolation(
                        "unsorted_preselection_source",
                        "candidate-independent source coordinates must be unique and sorted",
                )
                previous_coordinate = coordinate
                day_rows[index] = canonical
            for offset in range(0, len(day_rows), batch_rows):
                table = pa.Table.from_pylist(
                    day_rows[offset : offset + batch_rows],
                    schema=PRODUCTION_PRESELECTION_SOURCE_ARROW_SCHEMA,
                )
                if writer is None:
                    writer = pq.ParquetWriter(
                        temp_out,
                        PRODUCTION_PRESELECTION_SOURCE_ARROW_SCHEMA,
                        compression="zstd",
                    )
                writer.write_table(table)
            row_count += len(day_rows)
            market_days += 1
            observed_market_day_counts[day_market_day] += len(day_rows)
            day_rows = None
    except BaseException:
        if writer is not None:
            writer.close()
            writer = None
        if temp_out.exists():
            temp_out.unlink()
        if temp_manifest.exists():
            temp_manifest.unlink()
        raise
    finally:
        if writer is not None:
            writer.close()
    if not row_count or not temp_out.exists():
        if temp_out.exists():
            temp_out.unlink()
        raise ContractViolation(
            "empty_preselection_source",
            "manifest-pinned replay produced no candidate-independent rows",
        )
    if (
        market_days != len(entries)
        or dict(observed_market_day_counts) != expected_market_day_counts
    ):
        temp_out.unlink(missing_ok=True)
        raise ContractViolation(
            "preselection_source_inventory_mismatch",
            "candidate-independent replay did not consume the exact manifest inventory",
        )

    inputs = [
        {
            "event_slug": str(entry.get("event_slug") or ""),
            "target_date": str(entry.get("target_date") or ""),
            "market_id": str(entry.get("market_id") or ""),
            "row_count": int(entry.get("row_count") or 0),
            "snapshot_count": int(entry.get("snapshot_count") or 0),
            "label_hash": str(entry.get("label_hash") or ""),
        }
        for entry in entries
    ]
    manifest = {
        "schema_version": PRODUCTION_PRESELECTION_SOURCE_SCHEMA_VERSION,
        "artifact_type": "production_point_in_time_preselection_source_manifest",
        "generated_at_utc": _generated_at_utc(generated_at_utc),
        "status": "PASS",
        "candidate_dependent_fields_included": [],
        "candidate_dependent_fields_absent": [
            "candidate_id",
            "variant_id",
            "release_id",
            "prediction_probability",
            "runtime_identity",
            "source_payload_json",
            "source_payload_sha256",
        ],
        "derived_artifact": {
            "path": str(parquet_out),
            "sha256": sha256_file(temp_out),
            "row_count": row_count,
            "bytes": temp_out.stat().st_size,
            "compression": "zstd",
        },
        "source_replay_manifest": {
            "path": str(replay_manifest),
            "sha256": replay_sha256,
            "corpus_hash": str(replay.get("corpus_hash") or ""),
        },
        "streaming_bounds": {
            "max_market_days": max_market_days,
            "max_rows_per_market_day": max_rows_per_market_day,
            "max_arrow_batch_rows": batch_rows,
            "max_replay_manifest_bytes": PRODUCTION_MAX_REPLAY_MANIFEST_BYTES,
            "max_source_manifest_bytes": PRODUCTION_MAX_SOURCE_MANIFEST_BYTES,
            "max_source_parquet_bytes": PRODUCTION_MAX_SOURCE_PARQUET_BYTES,
            "max_tape_bytes": PRODUCTION_MAX_TAPE_BYTES,
            "max_tape_field_bytes": PRODUCTION_MAX_TAPE_FIELD_BYTES,
            "max_replay_bytes": PRODUCTION_MAX_REPLAY_BYTES,
            "max_replay_line_bytes": PRODUCTION_MAX_REPLAY_LINE_BYTES,
            "max_settlement_bytes": PRODUCTION_MAX_SETTLEMENT_BYTES,
            "max_source_text_bytes": PRODUCTION_MAX_SOURCE_TEXT_BYTES,
            "raw_market_days_retained_at_once": 1,
        },
        "counts": {
            "market_days_read": market_days,
            "accepted_rows": row_count,
        },
        "inputs": inputs,
    }
    manifest["manifest_hash"] = sha256_text(canonical_json(manifest))
    temp_manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    published_corpus = False
    try:
        os.replace(temp_out, parquet_out)
        published_corpus = True
        os.replace(temp_manifest, manifest_out)
        verified = verify_production_preselection_source_manifest(
            parquet_out,
            manifest_out,
            replay_manifest=replay_manifest,
            batch_rows=batch_rows,
        )
    except BaseException:
        if published_corpus and parquet_out.exists():
            parquet_out.unlink()
        if manifest_out.exists():
            manifest_out.unlink()
        if temp_out.exists():
            temp_out.unlink()
        if temp_manifest.exists():
            temp_manifest.unlink()
        raise
    return verified


def verify_production_preselection_source_manifest(
    parquet_path: str | Path,
    manifest_path: str | Path,
    *,
    replay_manifest: str | Path | None = None,
    batch_rows: int = 65_536,
) -> dict[str, Any]:
    """Verify the narrow pre-candidate source, including its replay binding."""

    parquet_source_path = Path(parquet_path)
    if parquet_source_path.is_symlink():
        raise ContractViolation(
            "invalid_preselection_source_manifest",
            "production preselection source Parquet cannot be a symlink",
        )
    parquet_path = parquet_source_path.resolve()
    manifest_source_path = Path(manifest_path)
    manifest_path = manifest_source_path.resolve()
    if not 0 < int(batch_rows) <= 65_536:
        raise ValueError("batch_rows exceeds the production preselection bound")
    manifest = _read_bounded_contract_json(
        manifest_source_path,
        code="invalid_preselection_source_manifest",
        max_bytes=PRODUCTION_MAX_SOURCE_MANIFEST_BYTES,
    )
    if (
        manifest.get("schema_version")
        != PRODUCTION_PRESELECTION_SOURCE_SCHEMA_VERSION
        or manifest.get("artifact_type")
        != "production_point_in_time_preselection_source_manifest"
        or manifest.get("status") != "PASS"
        or manifest.get("candidate_dependent_fields_included") != []
        or set(manifest.get("candidate_dependent_fields_absent") or ())
        != {
            "candidate_id",
            "variant_id",
            "release_id",
            "prediction_probability",
            "runtime_identity",
            "source_payload_json",
            "source_payload_sha256",
        }
    ):
        raise ContractViolation(
            "invalid_preselection_source_manifest",
            "candidate-independent source manifest contract is incomplete",
        )
    _verify_self_hash(
        manifest,
        "manifest_hash",
        "preselection_source_manifest_hash_mismatch",
    )
    artifact = manifest.get("derived_artifact") or {}
    try:
        parquet_stat = parquet_path.stat()
    except OSError as exc:
        raise ContractViolation(
            "preselection_source_hash_mismatch",
            f"cannot inspect production source Parquet: {exc}",
        ) from exc
    if (
        not stat.S_ISREG(parquet_stat.st_mode)
        or parquet_stat.st_size <= 0
        or parquet_stat.st_size > PRODUCTION_MAX_SOURCE_PARQUET_BYTES
        or int(artifact.get("bytes") or -1) != parquet_stat.st_size
        or artifact.get("sha256") != sha256_file(parquet_path)
    ):
        raise ContractViolation(
            "preselection_source_hash_mismatch",
            "preselection source Parquet changed or exceeds its byte bound",
        )
    actual_rows = int(pq.ParquetFile(parquet_path).metadata.num_rows)
    if (
        actual_rows <= 0
        or actual_rows
        > PRODUCTION_MAX_MARKET_DAYS * PRODUCTION_MAX_ROWS_PER_MARKET_DAY
        or int(artifact.get("row_count") or -1) != actual_rows
    ):
        raise ContractViolation(
            "preselection_source_row_count_mismatch",
            "preselection source row count changed",
        )
    bounds = manifest.get("streaming_bounds") or {}
    if (
        not 0 < int(bounds.get("max_market_days") or 0) <= 60
        or not 0 < int(bounds.get("max_rows_per_market_day") or 0) <= 250_000
        or not 0 < int(bounds.get("max_arrow_batch_rows") or 0) <= 65_536
        or int(bounds.get("max_replay_manifest_bytes") or 0)
        != PRODUCTION_MAX_REPLAY_MANIFEST_BYTES
        or int(bounds.get("max_source_manifest_bytes") or 0)
        != PRODUCTION_MAX_SOURCE_MANIFEST_BYTES
        or int(bounds.get("max_source_parquet_bytes") or 0)
        != PRODUCTION_MAX_SOURCE_PARQUET_BYTES
        or int(bounds.get("max_tape_bytes") or 0) != PRODUCTION_MAX_TAPE_BYTES
        or int(bounds.get("max_tape_field_bytes") or 0)
        != PRODUCTION_MAX_TAPE_FIELD_BYTES
        or int(bounds.get("max_replay_bytes") or 0) != PRODUCTION_MAX_REPLAY_BYTES
        or int(bounds.get("max_replay_line_bytes") or 0)
        != PRODUCTION_MAX_REPLAY_LINE_BYTES
        or int(bounds.get("max_settlement_bytes") or 0)
        != PRODUCTION_MAX_SETTLEMENT_BYTES
        or int(bounds.get("max_source_text_bytes") or 0)
        != PRODUCTION_MAX_SOURCE_TEXT_BYTES
        or int(bounds.get("raw_market_days_retained_at_once") or 0) != 1
    ):
        raise ContractViolation(
            "invalid_point_in_time_resource_contract",
            "candidate-independent source streaming bounds are invalid",
        )
    previous_coordinate = None
    observed_rows = 0
    observed_market_day_counts: Counter[tuple[str, str]] = Counter()
    observed_snapshot_ids: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    observed_winner_counts: Counter[tuple[str, str, str]] = Counter()
    observed_winner_bands: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    observed_label_qualities: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    for row in iter_production_preselection_source_parquet(
        parquet_path, batch_rows=batch_rows
    ):
        coordinate = (
            row["target_date"],
            row["market_id"],
            row["cutoff_or_snapshot"],
            row["band"],
        )
        if previous_coordinate is not None and coordinate <= previous_coordinate:
            raise ContractViolation(
                "unsorted_preselection_source",
                "candidate-independent source coordinates are duplicated or unsorted",
            )
        previous_coordinate = coordinate
        observed_rows += 1
        market_day = (row["target_date"], row["market_id"])
        snapshot_id = row["cutoff_or_snapshot"]
        observed_market_day_counts[market_day] += 1
        observed_snapshot_ids[market_day].add(snapshot_id)
        observed_label_qualities[market_day].add(row["label_quality"])
        if float(row["label"]) == 1.0:
            observed_winner_counts[(*market_day, snapshot_id)] += 1
            observed_winner_bands[market_day].add(row["band"])
    input_market_day_counts: dict[tuple[str, str], int] = {}
    input_inventory: dict[tuple[str, str], tuple[str, int, int, str]] = {}
    for item in manifest.get("inputs") or ():
        key = (
            str(item.get("target_date") or ""),
            str(item.get("market_id") or ""),
        )
        item_rows = int(item.get("row_count") or 0)
        event_slug = str(item.get("event_slug") or "")
        label_hash = str(item.get("label_hash") or "")
        snapshot_count = int(item.get("snapshot_count") or 0)
        if (
            not all(key)
            or not event_slug
            or not SHA256_RE.fullmatch(label_hash)
            or key in input_market_day_counts
            or item_rows <= 0
            or not 0 < snapshot_count <= item_rows
        ):
            raise ContractViolation(
                "preselection_source_inventory_mismatch",
                "candidate-independent source input inventory is invalid",
            )
        input_market_day_counts[key] = item_rows
        input_inventory[key] = (
            event_slug,
            item_rows,
            snapshot_count,
            label_hash,
        )
    counts = manifest.get("counts") or {}
    if (
        observed_rows != actual_rows
        or int(counts.get("accepted_rows") or -1) != observed_rows
        or int(counts.get("market_days_read") or -1)
        != len(observed_market_day_counts)
        or dict(observed_market_day_counts) != input_market_day_counts
    ):
        raise ContractViolation(
            "preselection_source_inventory_mismatch",
            "candidate-independent source inventory changed",
        )
    replay_binding = manifest.get("source_replay_manifest") or {}
    replay_path = Path(
        replay_manifest or str(replay_binding.get("path") or "")
    ).resolve()
    replay = _load_production_replay_manifest(replay_path)
    replay_bytes = _read_bounded_contract_bytes(
        replay_path,
        code="preselection_source_replay_mismatch",
        max_bytes=PRODUCTION_MAX_REPLAY_MANIFEST_BYTES,
    )
    try:
        replay_as_of = date.fromisoformat(str(replay.get("as_of") or ""))
    except ValueError as exc:
        raise ContractViolation(
            "preselection_source_replay_mismatch",
            "candidate-independent replay has no valid as_of date",
        ) from exc
    replay_inventory = {}
    for item in replay.get("entries") or ():
        key = (
            str(item.get("target_date") or ""),
            str(item.get("market_id") or ""),
        )
        snapshot_ids = tuple(str(value) for value in item.get("snapshot_ids") or ())
        snapshot_id_set = set(snapshot_ids)
        row_count = int(item.get("row_count") or 0)
        snapshot_count = int(item.get("snapshot_count") or 0)
        label_hash = str(item.get("label_hash") or "")
        quality_grade = str(item.get("quality_grade") or "").strip().lower()
        winning_band = str(item.get("winning_band") or "").strip()
        try:
            target_date = date.fromisoformat(key[0])
        except ValueError as exc:
            raise ContractViolation(
                "preselection_source_replay_mismatch",
                "replay manifest contains an invalid target date",
            ) from exc
        if (
            key in replay_inventory
            or not all(key)
            or target_date >= replay_as_of
            or not 0 < row_count <= int(bounds["max_rows_per_market_day"])
            or not snapshot_ids
            or len(snapshot_id_set) != len(snapshot_ids)
            or snapshot_count != len(snapshot_ids)
            or snapshot_count > row_count
            or not SHA256_RE.fullmatch(label_hash)
            or quality_grade not in COUNTABLE_LABEL_QUALITIES
            or item.get("admitted_by") != "quality_grade"
            or not winning_band
            or set(item.get("replay_record_hashes") or {}) != snapshot_id_set
            or set(item.get("tape_row_hashes") or {}) != snapshot_id_set
            or any(
                not SHA256_RE.fullmatch(str(value or ""))
                for value in (item.get("replay_record_hashes") or {}).values()
            )
            or any(
                not SHA256_RE.fullmatch(str(value or ""))
                for value in (item.get("tape_row_hashes") or {}).values()
            )
        ):
            raise ContractViolation(
                "preselection_source_replay_mismatch",
                "replay manifest contains an invalid production market-day",
            )
        replay_inventory[key] = (
            str(item.get("event_slug") or ""),
            row_count,
            snapshot_count,
            label_hash,
        )
        if (
            observed_snapshot_ids.get(key, set()) != snapshot_id_set
            or observed_label_qualities.get(key, set()) != {quality_grade}
            or observed_winner_bands.get(key, set()) != {winning_band}
            or any(
                observed_winner_counts[(*key, snapshot_id)] != 1
                for snapshot_id in snapshot_ids
            )
        ):
            raise ContractViolation(
                "preselection_source_replay_mismatch",
                "source rows differ from the exact replay snapshot/label inventory",
            )
    if (
        hashlib.sha256(replay_bytes).hexdigest() != replay_binding.get("sha256")
        or replay.get("corpus_hash") != replay_binding.get("corpus_hash")
        or replay.get("include_reconstructed") is not False
        or replay.get("allow_unsettled") is not False
        or replay.get("admit_promotion_countable") is not False
        or len(replay_inventory) > int(bounds["max_market_days"])
        or replay_inventory != input_inventory
    ):
        raise ContractViolation(
            "preselection_source_replay_mismatch",
            "candidate-independent source differs from the exact replay inventory",
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
    fit_output_rows: Sequence[Mapping[str, Any]] | None = None,
    validation_output_rows: Sequence[Mapping[str, Any]] | None = None,
    stage_input_payload: Any = None,
    stage_output_payload: Any = None,
    upstream_stage_output_sha256: str | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build a training-only receipt, optionally binding stage inputs to outputs."""

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
    fit_input_sha = sha256_text(canonical_json([_jsonable(row) for row in fit_rows]))
    validation_input_sha = sha256_text(
        canonical_json([_jsonable(row) for row in validation_rows])
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
        "fit_input_sha256": fit_input_sha,
        "validation_input_sha256": validation_input_sha,
    }
    output_binding_requested = (
        fit_output_rows is not None
        or validation_output_rows is not None
        or stage_input_payload is not None
        or stage_output_payload is not None
        or upstream_stage_output_sha256 is not None
    )
    if output_binding_requested:
        if fit_output_rows is None or validation_output_rows is None:
            raise ValueError(
                "fit_output_rows and validation_output_rows are required for output binding"
            )
        if not fit_output_rows or not validation_output_rows:
            raise ValueError("fit and validation output rows cannot be empty")
        fit_output_dates = {
            str(row.get("target_date") or "") for row in fit_output_rows
        }
        validation_output_dates = {
            str(row.get("target_date") or "") for row in validation_output_rows
        }
        if (
            fit_output_dates != set(fold.train_dates)
            or validation_output_dates != set(fold.validation_dates)
        ):
            raise ContractViolation(
                "fit_receipt_output_date_mismatch",
                "fit receipt outputs do not exactly match the declared fold",
            )
        if upstream_stage_output_sha256 is not None and not SHA256_RE.fullmatch(
            str(upstream_stage_output_sha256)
        ):
            raise ValueError("upstream_stage_output_sha256 must be SHA-256 when supplied")
        fit_output_sha = sha256_text(
            canonical_json([_jsonable(row) for row in fit_output_rows])
        )
        validation_output_sha = sha256_text(
            canonical_json([_jsonable(row) for row in validation_output_rows])
        )
        declared_input = _jsonable(
            stage_input_payload
            if stage_input_payload is not None
            else {"kind": "training_only_stage_input"}
        )
        declared_output = _jsonable(
            stage_output_payload
            if stage_output_payload is not None
            else {"kind": "transformed_rows"}
        )
        input_payload = {
            "fit_input_sha256": fit_input_sha,
            "validation_input_sha256": validation_input_sha,
            "fit_row_count": len(fit_rows),
            "validation_row_count": len(validation_rows),
            "train_dates": list(fold.train_dates),
            "validation_dates": list(fold.validation_dates),
            "upstream_stage_output_sha256": upstream_stage_output_sha256,
            "declared_stage_input": declared_input,
        }
        output_payload = {
            "fit_output_sha256": fit_output_sha,
            "validation_output_sha256": validation_output_sha,
            "fit_output_row_count": len(fit_output_rows),
            "validation_output_row_count": len(validation_output_rows),
            "train_dates": list(fold.train_dates),
            "validation_dates": list(fold.validation_dates),
            "declared_stage_output": declared_output,
        }
        receipt.update({
            "payload_hash_algorithm": FIT_RECEIPT_PAYLOAD_HASH_ALGORITHM,
            "payload_canonicalization": FIT_RECEIPT_PAYLOAD_CANONICALIZATION,
            "fit_output_row_count": len(fit_output_rows),
            "validation_output_row_count": len(validation_output_rows),
            "fit_output_sha256": fit_output_sha,
            "validation_output_sha256": validation_output_sha,
            "stage_input_payload": input_payload,
            "stage_input_sha256": sha256_text(canonical_json(input_payload)),
            "stage_output_payload": output_payload,
            "stage_output_sha256": sha256_text(canonical_json(output_payload)),
        })
    return _finalize_hash(receipt, "receipt_sha256")


def _verify_output_bound_fit_receipt(receipt: Mapping[str, Any]) -> None:
    """Recompute one receipt's declared stage input and output payload hashes."""

    if (
        receipt.get("payload_hash_algorithm") != FIT_RECEIPT_PAYLOAD_HASH_ALGORITHM
        or receipt.get("payload_canonicalization")
        != FIT_RECEIPT_PAYLOAD_CANONICALIZATION
    ):
        raise ContractViolation(
            "invalid_fit_receipt_payload_binding",
            "fit receipt payload hash contract is missing",
        )
    input_payload = receipt.get("stage_input_payload")
    output_payload = receipt.get("stage_output_payload")
    if not isinstance(input_payload, Mapping) or not isinstance(output_payload, Mapping):
        raise ContractViolation(
            "invalid_fit_receipt_payload_binding",
            "fit receipt input/output payloads are missing",
        )
    input_sha = str(receipt.get("stage_input_sha256") or "")
    output_sha = str(receipt.get("stage_output_sha256") or "")
    if (
        not SHA256_RE.fullmatch(input_sha)
        or input_sha != sha256_text(canonical_json(input_payload))
    ):
        raise ContractViolation(
            "fit_receipt_input_payload_hash_mismatch",
            "fit receipt input payload hash does not recompute",
        )
    if (
        not SHA256_RE.fullmatch(output_sha)
        or output_sha != sha256_text(canonical_json(output_payload))
    ):
        raise ContractViolation(
            "fit_receipt_output_payload_hash_mismatch",
            "fit receipt output payload hash does not recompute",
        )
    expected_input = {
        "fit_input_sha256": receipt.get("fit_input_sha256"),
        "validation_input_sha256": receipt.get("validation_input_sha256"),
        "fit_row_count": receipt.get("fit_row_count"),
        "validation_row_count": receipt.get("validation_row_count"),
        "train_dates": list(receipt.get("train_dates") or ()),
        "validation_dates": list(receipt.get("validation_dates") or ()),
        "upstream_stage_output_sha256": input_payload.get(
            "upstream_stage_output_sha256"
        ),
        "declared_stage_input": input_payload.get("declared_stage_input"),
    }
    if dict(input_payload) != expected_input:
        raise ContractViolation(
            "invalid_fit_receipt_payload_binding",
            "fit receipt input payload is inconsistent with its receipt",
        )
    expected_output = {
        "fit_output_sha256": receipt.get("fit_output_sha256"),
        "validation_output_sha256": receipt.get("validation_output_sha256"),
        "fit_output_row_count": receipt.get("fit_output_row_count"),
        "validation_output_row_count": receipt.get("validation_output_row_count"),
        "train_dates": list(receipt.get("train_dates") or ()),
        "validation_dates": list(receipt.get("validation_dates") or ()),
        "declared_stage_output": output_payload.get("declared_stage_output"),
    }
    if dict(output_payload) != expected_output:
        raise ContractViolation(
            "invalid_fit_receipt_payload_binding",
            "fit receipt output payload is inconsistent with its receipt",
        )
    if (
        not SHA256_RE.fullmatch(str(receipt.get("fit_output_sha256") or ""))
        or not SHA256_RE.fullmatch(
            str(receipt.get("validation_output_sha256") or "")
        )
    ):
        raise ContractViolation(
            "invalid_fit_receipt_payload_binding",
            "fit receipt output row hashes are invalid",
        )
    try:
        output_counts_positive = (
            int(receipt.get("fit_output_row_count") or 0) > 0
            and int(receipt.get("validation_output_row_count") or 0) > 0
        )
    except (TypeError, ValueError):
        output_counts_positive = False
    if not output_counts_positive or output_payload.get("declared_stage_output") is None:
        raise ContractViolation(
            "invalid_fit_receipt_payload_binding",
            "fit receipt output declaration is incomplete",
        )


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
    upstream_stage_output_sha256: str | None = None
    for name, factory in hook_factories:
        if not str(name).strip():
            raise ValueError("training-only hook name is required")
        hook = factory()
        if hook is None:
            raise ValueError(f"hook factory returned None: {name}")
        hook.fit(train_state)
        transformed_train = tuple(hook.transform(train_state))
        transformed_validation = tuple(hook.transform(validation_state))
        implementation_identity = f"{type(hook).__module__}.{type(hook).__qualname__}"
        stage_output_declaration: Any = {
            "kind": "transformed_rows",
            "implementation_identity": implementation_identity,
        }
        receipt_output = getattr(hook, "receipt_output_payload", None)
        if callable(receipt_output):
            stage_output_declaration = receipt_output()
        receipt = build_fit_receipt(
            fold,
            fold_scope=fold_scope or f"outer/{fold.fold_id}",
            stage_name=str(name),
            implementation_identity=implementation_identity,
            fit_rows=train_state,
            validation_rows=validation_state,
            fit_output_rows=transformed_train,
            validation_output_rows=transformed_validation,
            stage_input_payload={
                "kind": "training_only_stage_input",
                "stage_name": str(name),
            },
            stage_output_payload=stage_output_declaration,
            upstream_stage_output_sha256=upstream_stage_output_sha256,
            generated_at_utc=generated_at_utc,
        )
        fit_receipts.append(receipt)
        upstream_stage_output_sha256 = str(receipt["stage_output_sha256"])
        train_state = transformed_train
        validation_state = transformed_validation
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
    require_output_bound_receipts: bool = False,
    selection_excluded_dates: Iterable[str | date] = (),
    selection_window_lock: Mapping[str, Any] | None = None,
    resource_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    dates = _unique_dates(fleet_dates)
    excluded_dates = _unique_dates(selection_excluded_dates)
    if not set(excluded_dates) <= set(dates):
        raise ValueError("selection-excluded dates must belong to the corpus")
    selection_dates = [item for item in dates if item not in set(excluded_dates)]
    nested = build_nested_rolling_origin_folds(
        selection_dates,
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
            "stage_order": list(stages),
            "required_fold_scopes": sorted(fold_scopes),
            "receipt_hash_field": "receipt_sha256",
            "payload_binding_required": bool(require_output_bound_receipts),
            "payload_hash_algorithm": FIT_RECEIPT_PAYLOAD_HASH_ALGORITHM,
            "payload_canonicalization": FIT_RECEIPT_PAYLOAD_CANONICALIZATION,
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
    if excluded_dates:
        window_lock = dict(selection_window_lock or {})
        locked_values = [item.isoformat() for item in excluded_dates]
        if list(window_lock.get("target_dates") or ()) != locked_values:
            raise ValueError("selection window lock does not match excluded dates")
        payload["candidate_selection_contract"] = {
            "status": "PASS",
            "window_lock_id": str(window_lock.get("window_lock_id") or ""),
            "window_locked_at_utc": str(window_lock.get("generated_at_utc") or ""),
            "locked_evaluation_dates": locked_values,
            "locked_dates_used_for_selection": False,
            "candidate_selection_permission": "forbidden",
            "selection_date_count": len(selection_dates),
        }
    if resource_contract is not None:
        payload["resource_contract"] = _jsonable(resource_contract)
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

    selection_contract = payload.get("candidate_selection_contract")
    if require_fit_receipts:
        if not isinstance(selection_contract, Mapping):
            raise ContractViolation(
                "invalid_candidate_selection_contract",
                "production validation plan is missing its locked selection contract",
            )
        locked_selection_dates = tuple(
            str(value)
            for value in selection_contract.get("locked_evaluation_dates") or ()
        )
        locked_set = set(locked_selection_dates)
        if (
            selection_contract.get("status") != "PASS"
            or len(locked_selection_dates) != 14
            or len(locked_set) != 14
            or selection_contract.get("locked_dates_used_for_selection") is not False
            or selection_contract.get("candidate_selection_permission") != "forbidden"
            or not str(selection_contract.get("window_lock_id") or "")
        ):
            raise ContractViolation(
                "invalid_candidate_selection_contract",
                "production candidate selection lock is incomplete",
            )
        for value in locked_selection_dates:
            _parse_date(value, "candidate_selection_contract.locked_date")
        if not locked_set <= set(fleet_dates):
            raise ContractViolation(
                "invalid_candidate_selection_contract",
                "locked selection dates escape the frozen corpus",
            )
        if any(
            locked_set
            & set(fold.train_dates + fold.embargo_dates + fold.validation_dates)
            for fold in scopes.values()
        ):
            raise ContractViolation(
                "locked_window_reused_for_selection",
                "locked evaluation dates appear in a model-selection fold",
            )
        locked_at = _parse_utc(
            selection_contract.get("window_locked_at_utc"),
            "candidate_selection_contract.window_locked_at_utc",
        )
        plan_generated = _parse_utc(
            payload.get("generated_at_utc"), "validation_plan.generated_at_utc"
        )
        if locked_at > plan_generated:
            raise ContractViolation(
                "window_locked_after_candidate_selection",
                "evaluation window was locked after the validation plan was selected",
            )
        resources = payload.get("resource_contract")
        if (
            not isinstance(resources, Mapping)
            or resources.get("corpus_read_mode") != "market_day_streaming"
            or int(resources.get("raw_market_days_retained_at_once") or 0) != 1
            or not 0 < int(resources.get("private_memory_budget_bytes") or 0) <= 8 * 1024**3
            or not 0 < int(resources.get("max_market_days") or 0) <= 60
            or not 0 < int(resources.get("max_fold_scopes") or 0) <= 128
        ):
            raise ContractViolation(
                "invalid_point_in_time_resource_contract",
                "production point-in-time resource bounds are missing or unsafe",
            )

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
    if require_fit_receipts and (
        tuple(stages) != REQUIRED_FIT_STAGES
        or receipt_contract.get("payload_binding_required") is not True
        or receipt_contract.get("payload_hash_algorithm")
        != FIT_RECEIPT_PAYLOAD_HASH_ALGORITHM
        or receipt_contract.get("payload_canonicalization")
        != FIT_RECEIPT_PAYLOAD_CANONICALIZATION
        or tuple(receipt_contract.get("stage_order") or ()) != REQUIRED_FIT_STAGES
    ):
        raise ContractViolation(
            "invalid_fit_receipts",
            "production fit receipt stage/output binding contract is incomplete",
        )
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
        has_payload_binding = any(
            field in receipt
            for field in (
                "stage_input_payload",
                "stage_input_sha256",
                "stage_output_payload",
                "stage_output_sha256",
            )
        )
        if require_fit_receipts or has_payload_binding:
            _verify_output_bound_fit_receipt(receipt)
        receipt_by_key[key] = receipt
    expected_keys = {(scope, stage) for scope in scopes for stage in stages}
    if require_fit_receipts and set(receipt_by_key) != expected_keys:
        raise ContractViolation(
            "invalid_fit_receipts", "fit receipts do not cover every fold and stage"
        )
    if require_fit_receipts:
        for scope in scopes:
            prior: Mapping[str, Any] | None = None
            for stage in stages:
                receipt = receipt_by_key[(scope, stage)]
                input_payload = receipt["stage_input_payload"]
                upstream = input_payload.get("upstream_stage_output_sha256")
                if prior is None:
                    if upstream is not None:
                        raise ContractViolation(
                            "fit_receipt_stage_chain_mismatch",
                            f"first fit stage declares an upstream output: {(scope, stage)}",
                        )
                elif (
                    upstream != prior.get("stage_output_sha256")
                    or receipt.get("fit_input_sha256")
                    != prior.get("fit_output_sha256")
                    or receipt.get("validation_input_sha256")
                    != prior.get("validation_output_sha256")
                    or receipt.get("fit_row_count")
                    != prior.get("fit_output_row_count")
                    or receipt.get("validation_row_count")
                    != prior.get("validation_output_row_count")
                ):
                    raise ContractViolation(
                        "fit_receipt_stage_chain_mismatch",
                        f"fit stage input is not bound to the prior output: {(scope, stage)}",
                    )
                prior = receipt
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
        manifest_sha256: str | None = None,
        candidate_artifact_sha256: str | None = None,
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
        normalized_manifest = str(manifest_sha256 or "").strip().lower()
        normalized_artifact = str(candidate_artifact_sha256 or "").strip().lower()
        for field_name, value in (
            ("manifest_sha256", normalized_manifest),
            ("candidate_artifact_sha256", normalized_artifact),
        ):
            if value and not SHA256_RE.fullmatch(value):
                raise ValueError(f"{field_name} must be a SHA-256 hex digest")
        if normalized_candidate is not None:
            payload["candidate_id"] = normalized_candidate
        if normalized_release is not None:
            payload["release_id"] = normalized_release
        if normalized_manifest:
            payload["manifest_sha256"] = normalized_manifest
        if normalized_artifact:
            payload["candidate_artifact_sha256"] = normalized_artifact
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
    manifest_sha256: str | None = None,
    candidate_artifact_sha256: str | None = None,
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
        manifest_sha256=manifest_sha256,
        candidate_artifact_sha256=candidate_artifact_sha256,
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


def _selection_universe_basis(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return the candidate-independent identity locked before training.

    Candidate/release identities, probabilities, runtime identity, and replay
    payloads are deliberately excluded. Labels, timestamps, and source quality
    remain bound so the post-training replay cannot silently change the
    evaluation population.
    """

    return {
        "target_date": str(row["target_date"]),
        "market_id": str(row["market_id"]),
        "cutoff_or_snapshot": str(row["cutoff_or_snapshot"]),
        "band": str(row["band"]),
        "feature_available_at_utc": str(row["feature_available_at_utc"]),
        "prediction_made_at_utc": str(
            row.get("prediction_made_at_utc")
            or row.get("prediction_boundary_at_utc")
            or ""
        ),
        "label_quality": str(row["label_quality"]),
        "countable": bool(row["countable"]),
        "claim_lane": str(row["claim_lane"]),
        "source_quality": (
            "countable"
            if str(row["source_quality"]) in COUNTABLE_SOURCE_QUALITIES
            else str(row["source_quality"])
        ),
        "label": row.get("label"),
    }


def selection_universe_contract(
    parquet_path: str | Path,
    *,
    batch_rows: int = 65_536,
) -> dict[str, Any]:
    """Hash one unique, countable weather-only row per evaluation coordinate."""

    digest = hashlib.sha256()
    row_count = 0
    dates: set[str] = set()
    previous_coordinate: tuple[str, str, str, str] | None = None
    parquet_schema = pq.ParquetFile(parquet_path).schema_arrow
    if parquet_schema.equals(
        PRODUCTION_PRESELECTION_SOURCE_ARROW_SCHEMA,
        check_metadata=False,
    ):
        rows = iter_production_preselection_source_parquet(
            parquet_path, batch_rows=batch_rows
        )
    else:
        rows = iter_point_in_time_parquet(parquet_path, batch_rows=batch_rows)
    for row in rows:
        if row.get("claim_lane") != "weather_only" or not row.get("countable"):
            continue
        coordinate = (
            str(row["target_date"]),
            str(row["market_id"]),
            str(row["cutoff_or_snapshot"]),
            str(row["band"]),
        )
        if previous_coordinate is not None and coordinate <= previous_coordinate:
            code = (
                "duplicate_selection_coordinate"
                if coordinate == previous_coordinate
                else "unsorted_selection_universe"
            )
            raise ContractViolation(
                code,
                "production source must contain one sorted weather-only row per coordinate",
            )
        previous_coordinate = coordinate
        basis = _selection_universe_basis(row)
        digest.update(canonical_json(basis).encode("utf-8"))
        digest.update(b"\n")
        row_count += 1
        dates.add(coordinate[0])
    if not row_count:
        raise ContractViolation(
            "empty_selection_universe",
            "production source has no countable weather-only rows",
        )
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "hash_algorithm": "sha256",
        "canonicalization": "canonical_json_lines",
        "sha256": digest.hexdigest(),
        "row_count": row_count,
        "fleet_dates": sorted(dates),
        "candidate_dependent_fields_excluded": [
            "variant_id",
            "release_id",
            "prediction_probability",
            "runtime_identity",
            "source_payload_json",
            "source_payload_sha256",
            "source_provenance_json",
        ],
    }


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
    input_kind: str = "corpus_sha256",
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
        "input_kind": str(input_kind),
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
    manifest_sha256: str | None = None,
    candidate_artifact_sha256: str | None = None,
    validation_plan_hash: str | None = None,
    window_lock: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = verify_materialization_manifest(
        parquet_path,
        manifest_path,
        expected_candidate_id=candidate_id,
        expected_release_id=release_id,
    )
    dates = collect_parquet_fleet_dates(parquet_path, batch_rows=batch_rows)
    corpus_sha256 = str((manifest.get("derived_artifact") or {}).get("sha256") or "")
    if window_lock is None:
        lock = build_window_lock(
            dates,
            input_sha256=corpus_sha256,
            window_days=window_days,
            window_end=window_end,
            generated_at_utc=generated_at_utc,
        )
    else:
        lock = dict(window_lock)
        input_kind = str(lock.get("input_kind") or "corpus_sha256")
        if input_kind == "selection_universe_sha256":
            expected_lock_input = selection_universe_contract(
                parquet_path,
                batch_rows=batch_rows,
            )["sha256"]
        elif input_kind == "corpus_sha256":
            expected_lock_input = corpus_sha256
        else:
            raise ContractViolation(
                "invalid_evaluation_window_lock",
                "preselected evaluation lock has an unsupported input kind",
            )
        if (
            lock.get("input_sha256") != expected_lock_input
            or int(lock.get("window_days") or 0) != int(window_days)
            or not set(str(value) for value in lock.get("target_dates") or ())
            <= set(dates)
        ):
            raise ContractViolation(
                "invalid_evaluation_window_lock",
                "preselected evaluation lock does not match the frozen corpus",
            )
        if window_end is not None and lock.get("window_end") != str(window_end):
            raise ContractViolation(
                "invalid_evaluation_window_lock",
                "preselected evaluation lock has the wrong window end",
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
        manifest_sha256=manifest_sha256,
        candidate_artifact_sha256=candidate_artifact_sha256,
        validation_plan_hash=validation_plan_hash,
        materialization_manifest_hash=str(manifest.get("manifest_hash") or ""),
    )
    payload.pop("evaluation_hash", None)
    payload["input"] = {
        "path": str(parquet_path),
        "sha256": corpus_sha256,
        "selection_universe_sha256": (
            lock["input_sha256"]
            if lock.get("input_kind") == "selection_universe_sha256"
            else None
        ),
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
    expected_manifest_sha256: str | None = None,
    expected_candidate_artifact_sha256: str | None = None,
    expected_corpus_sha256: str | None = None,
    expected_selection_universe_sha256: str | None = None,
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
    if (
        expected_manifest_sha256 is not None
        and payload.get("manifest_sha256") != expected_manifest_sha256
    ):
        raise ContractViolation(
            "streaming_evaluation_identity_mismatch",
            "immutable release manifest identity mismatch",
        )
    if (
        expected_candidate_artifact_sha256 is not None
        and payload.get("candidate_artifact_sha256")
        != expected_candidate_artifact_sha256
    ):
        raise ContractViolation(
            "streaming_evaluation_identity_mismatch",
            "candidate artifact identity mismatch",
        )

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
        "input_kind": lock.get("input_kind") or "corpus_sha256",
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
    lock_input_kind = str(lock.get("input_kind") or "corpus_sha256")
    if lock_input_kind == "corpus_sha256":
        if (
            expected_corpus_sha256 is not None
            and lock.get("input_sha256") != expected_corpus_sha256
        ):
            raise ContractViolation(
                "invalid_evaluation_window_lock", "window corpus hash mismatch"
            )
    elif lock_input_kind == "selection_universe_sha256":
        if (
            expected_selection_universe_sha256 is not None
            and lock.get("input_sha256") != expected_selection_universe_sha256
        ):
            raise ContractViolation(
                "invalid_evaluation_window_lock",
                "window selection-universe hash mismatch",
            )
    else:
        raise ContractViolation(
            "invalid_evaluation_window_lock", "window input kind is unsupported"
        )
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
        if max_age_days is not None:
            target_age_days = (
                (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
                - parsed_dates[-1]
            ).days
            if not 0 <= target_age_days <= max_age_days:
                raise ContractViolation(
                    "stale_streaming_evaluation_target_window",
                    "evaluation target window is stale or future-dated",
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
                    numeric_interval = {}
                    for field in ("point_estimate", "lower", "upper"):
                        value = interval.get(field)
                        try:
                            numeric_value = float(value)
                        except (OverflowError, TypeError, ValueError):
                            numeric_value = math.nan
                        if (
                            isinstance(value, bool)
                            or not isinstance(value, (int, float))
                            or not math.isfinite(numeric_value)
                        ):
                            raise ContractViolation(
                                "invalid_clustered_intervals",
                                "interval point_estimate/lower/upper must be "
                                "finite numbers",
                            )
                        numeric_interval[field] = numeric_value
                    if not (
                        numeric_interval["lower"]
                        <= numeric_interval["point_estimate"]
                        <= numeric_interval["upper"]
                    ):
                        raise ContractViolation(
                            "invalid_clustered_intervals",
                            "interval bounds do not contain the point estimate",
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
        payload = json.loads(
            Path(path).read_text(encoding="utf-8"),
            parse_constant=_reject_nonfinite_json_constant,
            object_pairs_hook=_reject_duplicate_json_pairs,
        )
        _reject_nested_nonfinite_json(payload)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractViolation(code, f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractViolation(code, f"{path} must contain a JSON object")
    return payload


def _reject_duplicate_json_pairs(pairs):
    payload = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key {key!r}")
        payload[key] = value
    return payload


def _reject_nonfinite_json_constant(value):
    raise ValueError(f"non-finite JSON value {value}")


def _reject_nested_nonfinite_json(value: Any, *, path: str = "$") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite JSON number at {path}")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_nested_nonfinite_json(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_nested_nonfinite_json(item, path=f"{path}[{index}]")


def _read_bounded_contract_json(
    path: str | Path,
    *,
    code: str,
    max_bytes: int,
) -> dict[str, Any]:
    """Read a small production control artifact without an unbounded parse."""

    path = Path(path)
    raw = _read_bounded_contract_bytes(path, code=code, max_bytes=max_bytes)
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_nonfinite_json_constant,
            object_pairs_hook=_reject_duplicate_json_pairs,
        )
        _reject_nested_nonfinite_json(payload)
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractViolation(code, f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractViolation(code, f"{path} must contain a JSON object")
    return payload


def _read_bounded_contract_bytes(
    path: str | Path,
    *,
    code: str,
    max_bytes: int,
) -> bytes:
    path = Path(path)
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if path.is_symlink():
        raise ContractViolation(code, f"{path} cannot be a symlink")
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_size <= 0
                or before.st_size > max_bytes
            ):
                raise ContractViolation(
                    code,
                    f"{path} must be between 1 and {max_bytes} bytes",
                )
            raw = handle.read(max_bytes + 1)
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise ContractViolation(code, f"cannot read {path}: {exc}") from exc
    if (
        len(raw) != before.st_size
        or len(raw) > max_bytes
        or before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise ContractViolation(code, f"{path} changed during bounded read")
    return raw


def _verify_candidate_training_graph(
    graph: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    plan: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    selection_universe: Mapping[str, Any],
    expected_candidate_id: str,
    expected_release_id: str,
    expected_candidate_artifact_sha256: str | None = None,
    expected_calibration_artifact_sha256: str | None = None,
    expected_routing_artifact_sha256: str | None = None,
    expected_route_selection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify the immutable bridge from real trainer output to PIT scoring."""

    if (
        graph.get("schema_version") != CANDIDATE_TRAINING_GRAPH_SCHEMA_VERSION
        or graph.get("artifact_type") != "point_in_time_candidate_training_graph"
        or graph.get("status") != "PASS"
        or graph.get("candidate_id") != expected_candidate_id
        or graph.get("release_id") != expected_release_id
        or graph.get("locked_dates_used_for_selection") is not False
    ):
        raise ContractViolation(
            "invalid_candidate_training_graph",
            "candidate training graph identity or selection contract is invalid",
        )
    _verify_self_hash(
        graph,
        "graph_hash",
        "candidate_training_graph_hash_mismatch",
    )
    graph_hash = str(graph.get("graph_hash") or "")
    if (
        manifest.get("candidate_training_graph_hash") != graph_hash
        or manifest.get("candidate_training_graph") != graph
        or plan.get("candidate_training_graph_hash") != graph_hash
        or plan.get("candidate_training_graph") != graph
        or (evaluation.get("contract_binding") or {}).get(
            "candidate_training_graph_hash"
        )
        != graph_hash
    ):
        raise ContractViolation(
            "candidate_training_graph_mismatch",
            "materialization, plan, and evaluation do not share one training graph",
        )

    universe_sha = str(selection_universe.get("sha256") or "")
    evaluation_binding = evaluation.get("contract_binding") or {}
    if (
        graph.get("selection_universe_sha256") != universe_sha
        or evaluation_binding.get("selection_universe_sha256") != universe_sha
    ):
        raise ContractViolation(
            "candidate_training_population_mismatch",
            "candidate training graph is not bound to the replayed selection universe",
        )
    selection_contract = plan.get("candidate_selection_contract") or {}
    evaluation_lock = evaluation.get("window_lock") or {}
    stage_bindings = graph.get("selection_stage_bindings")
    locked_values = list(evaluation_lock.get("target_dates") or ())
    if (
        not isinstance(stage_bindings, Mapping)
        or set(stage_bindings) != {"calibration", "routing"}
        or graph.get("selection_stage_bindings_sha256")
        != sha256_text(canonical_json(stage_bindings))
        or any(
            not isinstance(binding, Mapping)
            or binding.get("preselection_hash") != graph.get("preselection_hash")
            or binding.get("window_lock_id") != graph.get("window_lock_id")
            or list(binding.get("locked_dates") or ()) != locked_values
            or binding.get("used_for_selection") is not False
            or not SHA256_RE.fullmatch(str(binding.get("binding_sha256") or ""))
            or not SHA256_RE.fullmatch(
                str(binding.get("source_folder_date_inventory_sha256") or "")
            )
            for binding in stage_bindings.values()
        )
    ):
        raise ContractViolation(
            "locked_window_reused_for_selection",
            "calibration or routing selection is not bound to the locked exclusion",
        )
    if (
        graph.get("window_lock_id") != evaluation_lock.get("window_lock_id")
        or selection_contract.get("window_lock_id")
        != evaluation_lock.get("window_lock_id")
        or evaluation_lock.get("input_kind") != "selection_universe_sha256"
        or evaluation_lock.get("input_sha256") != universe_sha
        or graph.get("preselection_hash")
        != manifest.get("preselection_hash")
    ):
        raise ContractViolation(
            "candidate_training_preselection_mismatch",
            "candidate graph does not preserve the preselected evaluation lock",
        )

    expected_folds_hash = sha256_text(canonical_json(plan.get("folds") or []))
    expected_receipts_hash = sha256_text(
        canonical_json(
            sorted(
                str(receipt.get("receipt_sha256") or "")
                for receipt in plan.get("fit_receipts") or ()
            )
        )
    )
    if (
        graph.get("folds_sha256") != expected_folds_hash
        or graph.get("fit_receipts_sha256") != expected_receipts_hash
        or not SHA256_RE.fullmatch(str(graph.get("final_fit_receipt_sha256") or ""))
        or not SHA256_RE.fullmatch(str(graph.get("training_evidence_sha256") or ""))
    ):
        raise ContractViolation(
            "candidate_training_evidence_mismatch",
            "folds or fit receipts differ from the real trainer evidence",
        )

    artifacts = graph.get("candidate_artifacts")
    if not isinstance(artifacts, Mapping) or any(
        not SHA256_RE.fullmatch(str(artifacts.get(key) or ""))
        for key in ("model_sha256", "calibration_sha256", "routing_sha256")
    ):
        raise ContractViolation(
            "invalid_candidate_training_graph",
            "candidate artifact hash inventory is incomplete",
        )
    expected_hashes = {
        "model_sha256": expected_candidate_artifact_sha256,
        "calibration_sha256": expected_calibration_artifact_sha256,
        "routing_sha256": expected_routing_artifact_sha256,
    }
    if any(
        expected is not None and artifacts.get(key) != expected
        for key, expected in expected_hashes.items()
    ):
        raise ContractViolation(
            "candidate_training_artifact_mismatch",
            "candidate training graph names a different fitted artifact",
        )
    if evaluation.get("candidate_artifact_sha256") != artifacts.get("model_sha256"):
        raise ContractViolation(
            "candidate_training_artifact_mismatch",
            "streaming evaluation did not score the graph's exact model artifact",
        )

    route_selection = graph.get("route_selection")
    if (
        not isinstance(route_selection, Mapping)
        or graph.get("route_selection_sha256")
        != sha256_text(canonical_json(route_selection))
        or (
            expected_route_selection is not None
            and dict(route_selection) != dict(expected_route_selection)
        )
    ):
        raise ContractViolation(
            "candidate_route_selection_mismatch",
            "candidate route decision is not bound to the training graph",
        )

    source_manifest_sha = str(graph.get("source_replay_manifest_sha256") or "")
    source_corpus_hash = str(graph.get("source_replay_corpus_hash") or "")
    inputs = manifest.get("inputs")
    if (
        not SHA256_RE.fullmatch(source_manifest_sha)
        or not SHA256_RE.fullmatch(source_corpus_hash)
        or not isinstance(inputs, list)
        or not inputs
        or any(
            not isinstance(row, Mapping)
            or row.get("source_mode")
            != "promotion_manifest_pinned_candidate_replay"
            or row.get("candidate_artifact_sha256") != artifacts.get("model_sha256")
            or row.get("source_replay_manifest_sha256") != source_manifest_sha
            or row.get("manifest_hash") != source_corpus_hash
            for row in inputs
        )
    ):
        raise ContractViolation(
            "candidate_replay_provenance_mismatch",
            "fresh replay inputs are not pinned to the graph's source and model",
        )

    resources = plan.get("resource_contract") or {}
    bounds = manifest.get("streaming_bounds") or {}
    declared_scopes = int(resources.get("max_fold_scopes") or 0)
    observed_scopes = sum(1 + len(row.get("inner") or ()) for row in plan.get("folds") or ())
    declared_days = int(resources.get("max_market_days") or 0)
    declared_rows = int(resources.get("max_rows_per_market_day") or 0)
    if (
        int(resources.get("observed_fold_scopes") or 0) != observed_scopes
        or observed_scopes > declared_scopes
        or not 0 < declared_days <= PRODUCTION_MAX_MARKET_DAYS
        or not 0 < declared_rows <= PRODUCTION_MAX_ROWS_PER_MARKET_DAY
        or int(resources.get("observed_market_days") or 0)
        != int(bounds.get("observed_market_days") or 0)
        or int(resources.get("observed_peak_rows_per_market_day") or 0)
        != int(bounds.get("observed_peak_rows_per_market_day") or 0)
        or int(bounds.get("observed_market_days") or 0)
        > declared_days
        or int(bounds.get("observed_peak_rows_per_market_day") or 0)
        > declared_rows
    ):
        raise ContractViolation(
            "invalid_point_in_time_resource_contract",
            "observed production replay or fold usage exceeds its declared bound",
        )
    return dict(graph)


def verify_production_point_in_time_artifacts(
    *,
    corpus_path: str | Path,
    materialization_manifest_path: str | Path,
    validation_plan_path: str | Path,
    streaming_evaluation_path: str | Path,
    expected_candidate_id: str,
    expected_release_id: str,
    expected_candidate_artifact_sha256: str | None = None,
    expected_calibration_artifact_sha256: str | None = None,
    expected_routing_artifact_sha256: str | None = None,
    expected_route_selection: Mapping[str, Any] | None = None,
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
    selection_universe = selection_universe_contract(corpus_path)
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
    graph = manifest.get("candidate_training_graph")
    if not isinstance(graph, Mapping):
        raise ContractViolation(
            "invalid_candidate_training_graph",
            "production materialization is missing the real trainer graph",
        )
    verified_graph = _verify_candidate_training_graph(
        graph,
        manifest=manifest,
        plan=plan,
        evaluation=evaluation,
        selection_universe=selection_universe,
        expected_candidate_id=expected_candidate_id,
        expected_release_id=expected_release_id,
        expected_candidate_artifact_sha256=expected_candidate_artifact_sha256,
        expected_calibration_artifact_sha256=expected_calibration_artifact_sha256,
        expected_routing_artifact_sha256=expected_routing_artifact_sha256,
        expected_route_selection=expected_route_selection,
    )
    verify_streaming_evaluation_payload(
        evaluation,
        expected_candidate_id=expected_candidate_id,
        expected_release_id=expected_release_id,
        expected_corpus_sha256=corpus_sha,
        expected_selection_universe_sha256=selection_universe["sha256"],
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
    if (
        not locked_dates <= set(fleet_dates)
        or (evaluation.get("window_lock") or {}).get("window_end")
        != max(fleet_dates)
    ):
        raise ContractViolation(
            "streaming_evaluation_corpus_mismatch", "locked dates escape the frozen corpus"
        )
    selection_contract = plan.get("candidate_selection_contract") or {}
    evaluation_lock = evaluation.get("window_lock") or {}
    if (
        set(selection_contract.get("locked_evaluation_dates") or ()) != locked_dates
        or selection_contract.get("window_lock_id")
        != evaluation_lock.get("window_lock_id")
        or selection_contract.get("window_locked_at_utc")
        != evaluation_lock.get("generated_at_utc")
    ):
        raise ContractViolation(
            "locked_window_reused_for_selection",
            "candidate-selection exclusion is not bound to the evaluated window",
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
        "fit_receipt_output_binding_verified": True,
        "candidate_training_graph_hash": verified_graph["graph_hash"],
        "candidate_artifacts": dict(verified_graph["candidate_artifacts"]),
        "selection_universe_sha256": selection_universe["sha256"],
    }


PRODUCTION_PRIVATE_MEMORY_BUDGET_BYTES = 4 * 1024**3
PRODUCTION_HOST_PHYSICAL_MEMORY_BYTES = int(15.7 * 1024**3)
PRODUCTION_MAX_FOLD_SCOPES = 128
PRODUCTION_MAX_MARKET_DAYS = 60
PRODUCTION_MAX_ROWS_PER_MARKET_DAY = 250_000
PRODUCTION_MAX_ARROW_BATCH_ROWS = 65_536
PRODUCTION_MAX_LATEST_TARGET_AGE_DAYS = 7
PRODUCTION_MAX_REPLAY_MANIFEST_BYTES = 16 * 1024**2
PRODUCTION_MAX_SOURCE_MANIFEST_BYTES = 4 * 1024**2
PRODUCTION_MAX_SOURCE_PARQUET_BYTES = 1024**3
PRODUCTION_MAX_TAPE_BYTES = 128 * 1024**2
PRODUCTION_MAX_TAPE_FIELD_BYTES = 1024**2
PRODUCTION_MAX_REPLAY_BYTES = 64 * 1024**2
PRODUCTION_MAX_REPLAY_LINE_BYTES = 8 * 1024**2
PRODUCTION_MAX_SETTLEMENT_BYTES = 1024**2
PRODUCTION_MAX_SOURCE_TEXT_BYTES = 1024


def _load_production_replay_manifest(path: str | Path) -> dict[str, Any]:
    return load_promotion_corpus_manifest(
        path,
        max_bytes=PRODUCTION_MAX_REPLAY_MANIFEST_BYTES,
    )


def _verify_production_latest_target_freshness(
    fleet_dates: Sequence[str],
    *,
    locked_at_utc: str,
    require_current_prelock: bool,
) -> int:
    if not fleet_dates:
        raise ContractViolation(
            "stale_point_in_time_preselection",
            "production selection universe has no latest target date",
        )
    locked_at = _parse_utc(locked_at_utc, "preselection.generated_at_utc")
    try:
        latest_target = date.fromisoformat(str(fleet_dates[-1]))
    except ValueError as exc:
        raise ContractViolation(
            "stale_point_in_time_preselection",
            "production selection universe latest target date is invalid",
        ) from exc
    target_age_days = (locked_at.date() - latest_target).days
    if not 0 <= target_age_days <= PRODUCTION_MAX_LATEST_TARGET_AGE_DAYS:
        raise ContractViolation(
            "stale_point_in_time_preselection",
            "production selection universe latest target date is stale or future-dated",
        )
    if require_current_prelock:
        now = datetime.now(timezone.utc)
        if locked_at > now or now - locked_at > timedelta(
            days=PRODUCTION_MAX_LATEST_TARGET_AGE_DAYS
        ):
            raise ContractViolation(
                "stale_point_in_time_preselection",
                "production preselection lock is too old or future-dated",
            )
    return target_age_days


def _verify_preselection_source_corpus(
    source_corpus: str | Path,
    source_manifest: str | Path,
    *,
    replay_manifest: str | Path | None = None,
    batch_rows: int = 65_536,
) -> dict[str, Any]:
    payload = _read_bounded_contract_json(
        source_manifest,
        code="invalid_materialization_manifest",
        max_bytes=PRODUCTION_MAX_SOURCE_MANIFEST_BYTES,
    )
    if (
        payload.get("artifact_type")
        == "production_point_in_time_preselection_source_manifest"
    ):
        return verify_production_preselection_source_manifest(
            source_corpus,
            source_manifest,
            replay_manifest=replay_manifest,
            batch_rows=batch_rows,
        )
    raise ContractViolation(
        "candidate_dependent_preselection_source",
        "production preselection requires the narrow candidate-independent source schema",
    )


def prepare_production_preselection(
    *,
    source_corpus: str | Path,
    source_manifest: str | Path,
    replay_manifest: str | Path,
    lock_out: str | Path,
    window_end: str | date | None = None,
    batch_rows: int = 65_536,
    max_market_days: int = 60,
    max_rows_per_market_day: int = 250_000,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Freeze the candidate-independent evaluation population before training."""

    if (
        not 0 < int(batch_rows) <= PRODUCTION_MAX_ARROW_BATCH_ROWS
        or not 0 < int(max_market_days) <= PRODUCTION_MAX_MARKET_DAYS
        or not 0
        < int(max_rows_per_market_day)
        <= PRODUCTION_MAX_ROWS_PER_MARKET_DAY
    ):
        raise ContractViolation(
            "invalid_point_in_time_resource_contract",
            "preselection request exceeds the production streaming bounds",
        )
    source_corpus = Path(source_corpus).resolve()
    source_manifest = Path(source_manifest).resolve()
    replay_manifest = Path(replay_manifest).resolve()
    manifest = _verify_preselection_source_corpus(
        source_corpus,
        source_manifest,
        replay_manifest=replay_manifest,
        batch_rows=batch_rows,
    )
    bounds = manifest.get("streaming_bounds") or {}
    if (
        not 0 < int(batch_rows) <= PRODUCTION_MAX_ARROW_BATCH_ROWS
        or not 0 < int(max_market_days) <= PRODUCTION_MAX_MARKET_DAYS
        or not 0
        < int(max_rows_per_market_day)
        <= PRODUCTION_MAX_ROWS_PER_MARKET_DAY
        or not 0 < int(bounds.get("max_market_days") or 0) <= int(max_market_days)
        or not 0 < int(bounds.get("max_rows_per_market_day") or 0)
        <= int(max_rows_per_market_day)
        or int(bounds.get("raw_market_days_retained_at_once") or 0) != 1
    ):
        raise ContractViolation(
            "invalid_point_in_time_resource_contract",
            "preselection source does not satisfy the production streaming bounds",
        )
    universe = selection_universe_contract(source_corpus, batch_rows=batch_rows)
    try:
        replay = _load_production_replay_manifest(replay_manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ContractViolation(
            "invalid_candidate_replay_manifest",
            f"cannot verify the preselection replay manifest: {exc}",
        ) from exc
    replay_entries = replay.get("entries") or []
    replay_dates = {str(row.get("target_date") or "") for row in replay_entries}
    if (
        not replay_entries
        or len(replay_entries) > int(max_market_days)
        or replay_dates != set(universe["fleet_dates"])
        or any(
            int(row.get("row_count") or 0) <= 0
            or int(row.get("row_count") or 0) > int(max_rows_per_market_day)
            for row in replay_entries
        )
    ):
        raise ContractViolation(
            "candidate_replay_manifest_population_mismatch",
            "replay manifest must cover exactly the bounded preselection fleet dates",
        )
    lock = build_window_lock(
        universe["fleet_dates"],
        input_sha256=universe["sha256"],
        input_kind="selection_universe_sha256",
        window_days=14,
        window_end=window_end,
        generated_at_utc=generated_at_utc,
    )
    if lock["status"] != "PASS":
        raise ContractViolation(
            "invalid_evaluation_window_lock",
            "production preselection requires a contiguous 14-day window",
        )
    if lock["window_end"] != universe["fleet_dates"][-1]:
        raise ContractViolation(
            "invalid_evaluation_window_lock",
            "production preselection must lock the most recent fleet date",
        )
    _verify_production_latest_target_freshness(
        universe["fleet_dates"],
        locked_at_utc=lock["generated_at_utc"],
        require_current_prelock=generated_at_utc is None,
    )
    payload = _finalize_hash(
        {
            "schema_version": PRODUCTION_PRESELECTION_SCHEMA_VERSION,
            "artifact_type": "production_point_in_time_preselection",
            "generated_at_utc": lock["generated_at_utc"],
            "status": "PASS",
            "candidate_selection_permission": "forbidden",
            "locked_before_candidate_training": True,
            "source": {
                "corpus_path": str(source_corpus),
                "corpus_sha256": sha256_file(source_corpus),
                "manifest_path": str(source_manifest),
                "manifest_sha256": sha256_file(source_manifest),
                "manifest_hash": str(manifest["manifest_hash"]),
                "replay_manifest_path": str(replay_manifest),
                "replay_manifest_sha256": sha256_file(replay_manifest),
                "replay_corpus_hash": str(replay["corpus_hash"]),
            },
            "selection_universe": universe,
            "window_lock": lock,
        },
        "preselection_hash",
    )
    _atomic_write_json(lock_out, payload)
    return payload


def verify_production_preselection(
    preselection_path: str | Path,
    *,
    source_corpus: str | Path | None = None,
    source_manifest: str | Path | None = None,
    replay_manifest: str | Path | None = None,
    batch_rows: int = 65_536,
) -> dict[str, Any]:
    if not 0 < int(batch_rows) <= PRODUCTION_MAX_ARROW_BATCH_ROWS:
        raise ValueError(
            f"batch_rows must be between 1 and {PRODUCTION_MAX_ARROW_BATCH_ROWS}"
        )
    payload = _read_contract_json(
        preselection_path, code="invalid_point_in_time_preselection"
    )
    if (
        payload.get("schema_version") != PRODUCTION_PRESELECTION_SCHEMA_VERSION
        or payload.get("artifact_type") != "production_point_in_time_preselection"
        or payload.get("status") != "PASS"
        or payload.get("candidate_selection_permission") != "forbidden"
        or payload.get("locked_before_candidate_training") is not True
    ):
        raise ContractViolation(
            "invalid_point_in_time_preselection",
            "production preselection contract is incomplete",
        )
    _verify_self_hash(
        payload, "preselection_hash", "point_in_time_preselection_hash_mismatch"
    )
    locked_at_utc = str(payload.get("generated_at_utc") or "")
    _parse_utc(locked_at_utc, "preselection.generated_at_utc")
    source = payload.get("source") or {}
    corpus_path = Path(source_corpus or source.get("corpus_path") or "").resolve()
    manifest_path = Path(source_manifest or source.get("manifest_path") or "").resolve()
    replay_manifest_path = Path(
        replay_manifest or source.get("replay_manifest_path") or ""
    ).resolve()
    if (
        sha256_file(corpus_path) != source.get("corpus_sha256")
        or sha256_file(manifest_path) != source.get("manifest_sha256")
        or sha256_file(replay_manifest_path)
        != source.get("replay_manifest_sha256")
    ):
        raise ContractViolation(
            "point_in_time_preselection_source_mismatch",
            "preselection source corpus or manifest changed after the lock",
        )
    manifest = _verify_preselection_source_corpus(
        corpus_path,
        manifest_path,
        replay_manifest=replay_manifest_path,
        batch_rows=batch_rows,
    )
    if manifest.get("manifest_hash") != source.get("manifest_hash"):
        raise ContractViolation(
            "point_in_time_preselection_source_mismatch",
            "preselection materialization manifest identity changed",
        )
    try:
        replay = _load_production_replay_manifest(replay_manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ContractViolation(
            "point_in_time_preselection_source_mismatch",
            f"preselection replay manifest is invalid: {exc}",
        ) from exc
    if replay.get("corpus_hash") != source.get("replay_corpus_hash"):
        raise ContractViolation(
            "point_in_time_preselection_source_mismatch",
            "preselection replay corpus identity changed",
        )
    universe = selection_universe_contract(corpus_path, batch_rows=batch_rows)
    if universe != payload.get("selection_universe"):
        raise ContractViolation(
            "point_in_time_preselection_universe_mismatch",
            "candidate-independent selection universe changed after the lock",
        )
    _verify_production_latest_target_freshness(
        universe["fleet_dates"],
        locked_at_utc=locked_at_utc,
        require_current_prelock=True,
    )
    if {
        str(row.get("target_date") or "") for row in replay.get("entries") or ()
    } != set(universe["fleet_dates"]):
        raise ContractViolation(
            "point_in_time_preselection_universe_mismatch",
            "replay manifest fleet dates differ from the locked universe",
        )
    lock = payload.get("window_lock") or {}
    expected_lock = build_window_lock(
        universe["fleet_dates"],
        input_sha256=universe["sha256"],
        input_kind="selection_universe_sha256",
        window_days=14,
        window_end=lock.get("window_end"),
        generated_at_utc=lock.get("generated_at_utc"),
    )
    if (
        lock != expected_lock
        or lock.get("status") != "PASS"
        or lock.get("window_end") != universe["fleet_dates"][-1]
    ):
        raise ContractViolation(
            "invalid_evaluation_window_lock",
            "preselection window lock is invalid or not the most recent window",
        )
    return payload


def _promotion_route_selection(payload: Mapping[str, Any]) -> dict[str, Any]:
    decisions = payload.get("decisions") or {}
    promote = sorted({str(value) for value in decisions.get("promote_markets") or ()})
    shadow = sorted({str(value) for value in decisions.get("shadow_markets") or ()})
    blocked = sorted({str(value) for value in decisions.get("blocked_markets") or ()})
    if blocked:
        verdict = "blocked"
    elif promote:
        verdict = "promote_ready"
    else:
        verdict = "shadow"
    return {
        "verdict": verdict,
        "promote_markets": promote,
        "shadow_markets": shadow,
        "blocked_markets": blocked,
    }


def _verified_stage_selection_binding(
    payload: Mapping[str, Any],
    *,
    preselection: Mapping[str, Any],
    stage: str,
) -> dict[str, Any]:
    binding = payload.get("point_in_time_selection_binding")
    if not isinstance(binding, Mapping):
        raise ContractViolation(
            "candidate_selection_binding_missing",
            f"{stage} artifact has no production preselection proof",
        )
    _verify_self_hash(
        binding,
        "binding_sha256",
        "candidate_selection_binding_hash_mismatch",
    )
    inventory = binding.get("source_inventory")
    if not isinstance(inventory, Mapping):
        raise ContractViolation(
            "candidate_selection_binding_invalid",
            f"{stage} source inventory is missing",
        )
    unhashed_inventory = dict(inventory)
    inventory_sha = str(unhashed_inventory.pop("sha256", "") or "")
    if (
        not SHA256_RE.fullmatch(inventory_sha)
        or inventory_sha != sha256_text(canonical_json(unhashed_inventory))
        or binding.get("source_folder_date_inventory_sha256") != inventory_sha
    ):
        raise ContractViolation(
            "candidate_selection_binding_invalid",
            f"{stage} source inventory hash is invalid",
        )
    expected_locked_dates = list(preselection["window_lock"]["target_dates"])
    inventory_dates: set[str] = set()
    pending: list[Any] = [inventory]
    while pending:
        value = pending.pop()
        if isinstance(value, Mapping):
            target_date = value.get("target_date")
            if target_date not in (None, ""):
                try:
                    inventory_dates.add(date.fromisoformat(str(target_date)).isoformat())
                except ValueError as exc:
                    raise ContractViolation(
                        "candidate_selection_binding_invalid",
                        f"{stage} source inventory has an invalid target date",
                    ) from exc
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)
    overlap = sorted(set(expected_locked_dates) & inventory_dates)
    if overlap:
        raise ContractViolation(
            "locked_window_reused_for_selection",
            f"{stage} source inventory includes locked dates: {', '.join(overlap)}",
        )
    universe_dates = set(
        preselection["selection_universe"]["fleet_dates"]
    )
    outside_universe = sorted(inventory_dates - universe_dates)
    if outside_universe:
        raise ContractViolation(
            "candidate_selection_binding_invalid",
            f"{stage} source inventory includes dates outside the immutable "
            f"selection universe: {', '.join(outside_universe)}",
        )
    if stage == "routing" and inventory_dates != (
        universe_dates - set(expected_locked_dates)
    ):
        raise ContractViolation(
            "candidate_selection_binding_invalid",
            "routing source inventory does not exactly cover the unlocked "
            "immutable selection universe",
        )
    if (
        binding.get("preselection_hash") != preselection["preselection_hash"]
        or binding.get("window_lock_id")
        != preselection["window_lock"]["window_lock_id"]
        or list(binding.get("locked_dates") or ()) != expected_locked_dates
        or binding.get("used_for_selection") is not False
    ):
        raise ContractViolation(
            "locked_window_reused_for_selection",
            f"{stage} selection is not bound to the preselected exclusion window",
        )
    return {
        "preselection_hash": binding["preselection_hash"],
        "window_lock_id": binding["window_lock_id"],
        "locked_dates": expected_locked_dates,
        "used_for_selection": False,
        "binding_sha256": binding["binding_sha256"],
        "source_folder_date_inventory_sha256": inventory_sha,
    }


def _candidate_training_graph(
    *,
    candidate_id: str,
    release_id: str,
    preselection: Mapping[str, Any],
    training_evidence: Mapping[str, Any],
    model_artifact: str | Path,
    calibration_artifact: str | Path,
    routing_artifact: str | Path,
) -> dict[str, Any]:
    routing_payload = _read_contract_json(
        routing_artifact,
        code="invalid_candidate_routing_artifact",
    )
    calibration_payload = _read_contract_json(
        calibration_artifact,
        code="invalid_candidate_calibration_artifact",
    )
    try:
        from weather.calibration.family_secondary_artifacts import (
            verify_production_family_manifest,
        )

        verify_production_family_manifest(calibration_payload, preselection)
    except (OSError, TypeError, ValueError) as exc:
        raise ContractViolation(
            "invalid_candidate_calibration_artifact",
            f"production family-secondary artifact is invalid: {exc}",
        ) from exc
    selection_stage_bindings = {
        "calibration": _verified_stage_selection_binding(
            calibration_payload,
            preselection=preselection,
            stage="calibration",
        ),
        "routing": _verified_stage_selection_binding(
            routing_payload,
            preselection=preselection,
            stage="routing",
        ),
    }
    receipts = training_evidence.get("fit_receipts") or []
    final_receipt = training_evidence.get("final_fit_receipt") or {}
    payload = {
        "schema_version": CANDIDATE_TRAINING_GRAPH_SCHEMA_VERSION,
        "artifact_type": "point_in_time_candidate_training_graph",
        "status": "PASS",
        "candidate_id": candidate_id,
        "release_id": release_id,
        "preselection_hash": preselection["preselection_hash"],
        "window_lock_id": preselection["window_lock"]["window_lock_id"],
        "selection_universe_sha256": preselection["selection_universe"]["sha256"],
        "training_evidence_sha256": training_evidence["evidence_sha256"],
        "training_evidence_generated_at_utc": training_evidence["generated_at_utc"],
        "folds_sha256": sha256_text(canonical_json(training_evidence["folds"])),
        "fit_receipts_sha256": sha256_text(
            canonical_json(sorted(str(row["receipt_sha256"]) for row in receipts))
        ),
        "final_fit_receipt_sha256": final_receipt["receipt_sha256"],
        "candidate_artifacts": {
            "model_sha256": sha256_file(model_artifact),
            "calibration_sha256": sha256_file(calibration_artifact),
            "routing_sha256": sha256_file(routing_artifact),
        },
        "route_selection": _promotion_route_selection(routing_payload),
        "route_selection_sha256": sha256_text(
            canonical_json(_promotion_route_selection(routing_payload))
        ),
        "selection_stage_bindings": selection_stage_bindings,
        "selection_stage_bindings_sha256": sha256_text(
            canonical_json(selection_stage_bindings)
        ),
        "source_replay_manifest_sha256": preselection["source"][
            "replay_manifest_sha256"
        ],
        "source_replay_corpus_hash": preselection["source"][
            "replay_corpus_hash"
        ],
        "locked_dates_used_for_selection": False,
    }
    return _finalize_hash(payload, "graph_hash")


def _sha256_canonical_sorted_strings(values: Iterable[str]) -> str:
    """Hash a canonical sorted JSON string list without joining day-sized text."""

    counts = Counter(str(value) for value in values)
    digest = hashlib.sha256()
    digest.update(b"[")
    first = True
    for value in sorted(counts):
        encoded = canonical_json(value).encode("utf-8")
        for _ in range(counts[value]):
            if not first:
                digest.update(b",")
            digest.update(encoded)
            first = False
    digest.update(b"]")
    return digest.hexdigest()


def _candidate_replay_input_row(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    first = rows[0]
    canonical_rows_digest = hashlib.sha256()
    for row in rows:
        canonical_rows_digest.update(canonical_json(row).encode("utf-8"))
        canonical_rows_digest.update(b"\n")
    canonical_rows_sha = canonical_rows_digest.hexdigest()
    replay_hash = _sha256_canonical_sorted_strings(
        str((row.get("source_lineage") or {}).get("replay_record_sha256") or "")
        for row in rows
    )
    tape_hash = _sha256_canonical_sorted_strings(
        str(
            (row.get("source_lineage") or {}).get("snapshot_tape_rows_sha256")
            or ""
        )
        for row in rows
    )
    label_hashes = {
        str((row.get("source_lineage") or {}).get("settlement_label_sha256") or "")
        for row in rows
    }
    return {
        "folder": str((first.get("source_lineage") or {}).get("market_day_folder") or ""),
        "target_date": str(first["target_date"]),
        "market_id": str(first["market_id"]),
        "artifact_family": "bounded_pooled_band_candidate_replay",
        "source_mode": "promotion_manifest_pinned_candidate_replay",
        "source_row_count": len(rows),
        "source_file_hash": replay_hash,
        "parquet_file_hash": canonical_rows_sha,
        "manifest_hash": str(first["source_corpus_hash"]),
        "event_manifest_hash": (
            next(iter(label_hashes)) if len(label_hashes) == 1 else ""
        ),
        "release_id": str(first["release_id"]),
        "runtime_identity_key": str(first["runtime_identity"]),
        "fallback_reason": None,
        "candidate_artifact_sha256": str(first["candidate_artifact_sha256"]),
        "source_replay_manifest_sha256": str(first["source_manifest_sha256"]),
        "replay_record_set_sha256": replay_hash,
        "tape_row_set_sha256": tape_hash,
    }


def _materialize_bounded_candidate_replay(
    *,
    candidate_id: str,
    release_id: str,
    corpus_out: str | Path,
    manifest_out: str | Path,
    model_artifact: str | Path,
    preselection_lock: str | Path,
    replay_manifest: str | Path,
    snapshots_root: str | Path,
    fleet_dates: Sequence[str],
    training_graph: Mapping[str, Any],
    max_market_days: int,
    max_rows_per_market_day: int,
    batch_rows: int,
) -> dict[str, Any]:
    corpus_out = Path(corpus_out).resolve()
    manifest_out = Path(manifest_out).resolve()
    if corpus_out.exists() or manifest_out.exists():
        raise FileExistsError("production candidate point-in-time outputs must be new")
    corpus_out.parent.mkdir(parents=True, exist_ok=True)
    temp = corpus_out.with_name(f".{corpus_out.name}.{os.getpid()}.tmp")
    writer: pq.ParquetWriter | None = None
    accepted_rows = 0
    peak_rows = 0
    peak_arrow_rows = 0
    label_qualities: Counter[str] = Counter()
    source_qualities: Counter[str] = Counter()
    input_rows: list[dict[str, Any]] = []
    arrow_batch_rows = min(
        max(1, int(batch_rows)),
        PRODUCTION_MAX_ARROW_BATCH_ROWS,
        int(max_rows_per_market_day),
    )

    def flush_day(day_rows: Sequence[Mapping[str, Any]]) -> None:
        nonlocal writer, accepted_rows, peak_rows, peak_arrow_rows
        if not day_rows:
            return
        if len(day_rows) > int(max_rows_per_market_day):
            raise BoundedReadError("candidate replay row bound exceeded")
        market_day = (
            str(day_rows[0].get("target_date") or ""),
            str(day_rows[0].get("market_id") or ""),
        )
        if not all(market_day):
            raise ContractViolation(
                "candidate_replay_population_mismatch",
                "candidate replay market-day identity is missing",
            )
        canonical_rows: list[dict[str, Any]] = []
        previous_key: tuple[str, ...] | None = None

        def write_arrow_batch() -> None:
            nonlocal writer, peak_arrow_rows
            if not canonical_rows:
                return
            table = pa.Table.from_pylist(
                canonical_rows,
                schema=POINT_IN_TIME_ARROW_SCHEMA,
            )
            if writer is None:
                writer = pq.ParquetWriter(
                    temp,
                    POINT_IN_TIME_ARROW_SCHEMA,
                    compression="zstd",
                )
            writer.write_table(table)
            peak_arrow_rows = max(peak_arrow_rows, len(canonical_rows))
            canonical_rows.clear()

        for raw in day_rows:
            coordinate = (
                str(raw.get("target_date") or ""),
                str(raw.get("market_id") or ""),
            )
            if coordinate != market_day:
                raise ContractViolation(
                    "candidate_replay_population_mismatch",
                    "candidate replay batch crosses a market-day boundary",
                )
            canonical = canonicalize_raw_row(
                raw,
                provenance=raw.get("source_lineage") or {},
                target_date=coordinate[0],
                market_id=coordinate[1],
                explicit_claim_lane="weather_only",
            )
            key = point_in_time_key(canonical)
            if previous_key is not None and key <= previous_key:
                raise ContractViolation(
                    "unsorted_selection_universe",
                    "candidate replay market-day batch is not strictly sorted",
                )
            previous_key = key
            canonical_rows.append(canonical)
            if len(canonical_rows) >= arrow_batch_rows:
                write_arrow_batch()
        write_arrow_batch()
        input_row = _candidate_replay_input_row(day_rows)
        input_rows.append(input_row)
        label_qualities.update(str(row["label_quality"]) for row in day_rows)
        source_qualities.update(str(row["source_quality"]) for row in day_rows)
        accepted_rows += len(day_rows)
        peak_rows = max(peak_rows, len(day_rows))

    replay_manifest_path = Path(replay_manifest).resolve()
    replay_manifest_sha = sha256_file(replay_manifest_path)
    iterator = iter_bounded_pooled_band_candidate_replay_market_days(
        artifact_path=model_artifact,
        expected_artifact_sha256=training_graph["candidate_artifacts"]["model_sha256"],
        candidate_id=candidate_id,
        release_id=release_id,
        corpus_manifest_path=replay_manifest_path,
        expected_manifest_sha256=replay_manifest_sha,
        preselection_lock_path=preselection_lock,
        expected_preselection_hash=training_graph["preselection_hash"],
        expected_window_lock_id=training_graph["window_lock_id"],
        snapshots_root=snapshots_root,
        locked_dates=fleet_dates,
        max_market_days=max_market_days,
        max_rows_per_market_day=max_rows_per_market_day,
    )
    try:
        for market_day_rows in iterator:
            flush_day(market_day_rows)
            # The producer cannot compute another market-day until its next
            # iteration.  Remove the consumer reference first so the completed
            # batch is reclaimable before that scorer invocation.
            del market_day_rows
    except BaseException:
        if writer is not None:
            writer.close()
            writer = None
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        raise
    finally:
        if writer is not None:
            writer.close()
    if not accepted_rows or len(input_rows) > int(max_market_days):
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        raise ContractViolation(
            "empty_candidate_replay",
            "bounded candidate replay produced no proof-grade rows",
        )
    os.replace(temp, corpus_out)
    manifest = {
        "schema_version": MATERIALIZER_SCHEMA_VERSION,
        "artifact_type": "point_in_time_materialization_manifest",
        "generated_at_utc": _utc_now_iso(),
        "status": "PASS",
        "candidate_id": candidate_id,
        "release_id": release_id,
        "row_key": list(KEY_FIELDS),
        "claim_lane_contract": list(CLAIM_LANES),
        "raw_evidence_mutated": False,
        "derived_artifact": {
            "path": str(corpus_out),
            "sha256": sha256_file(corpus_out),
            "row_count": accepted_rows,
            "bytes": corpus_out.stat().st_size,
            "compression": "zstd",
        },
        "transformation": {
            "version": TRANSFORMATION_VERSION,
            "source_artifact_family": "promotion_manifest_pinned_candidate_replay",
            "source_reader": (
                "weather.calibration.pooled_candidate_replay."
                "iter_bounded_pooled_band_candidate_replay_market_days"
            ),
            "settlement_join": "after_candidate_prediction",
        },
        "streaming_bounds": {
            "max_market_days": int(max_market_days),
            "max_rows_per_market_day": int(max_rows_per_market_day),
            "raw_market_days_retained_at_once": 1,
            "market_day_batch_handoff": "flush_before_next_compute",
            "arrow_write_batch_rows": arrow_batch_rows,
            "observed_market_days": len(input_rows),
            "observed_peak_rows_per_market_day": peak_rows,
            "observed_peak_arrow_rows": peak_arrow_rows,
        },
        "counts": {
            "market_days_read": len(input_rows),
            "source_rows": accepted_rows,
            "accepted_rows": accepted_rows,
            "excluded_rows": 0,
            "exclusions_by_reason": {},
            "source_modes": {
                "promotion_manifest_pinned_candidate_replay": accepted_rows
            },
            "label_qualities": dict(sorted(label_qualities.items())),
            "source_qualities": dict(sorted(source_qualities.items())),
            "claim_lanes": {"weather_only": accepted_rows},
        },
        "candidate_training_graph": dict(training_graph),
        "candidate_training_graph_hash": training_graph["graph_hash"],
        "preselection_hash": training_graph["preselection_hash"],
        "inputs": input_rows,
    }
    manifest["manifest_hash"] = sha256_text(canonical_json(manifest))
    _atomic_write_json(manifest_out, manifest)
    return manifest


def materialize_production_candidate_packet(
    *,
    candidate_id: str,
    release_id: str,
    corpus_out: str | Path,
    manifest_out: str | Path,
    validation_plan_out: str | Path,
    evaluation_out: str | Path,
    model_artifact: str | Path,
    calibration_artifact: str | Path,
    routing_artifact: str | Path,
    preselection_lock: str | Path,
    replay_manifest: str | Path,
    folders: Iterable[str | Path] = (),
    source_corpus: str | Path | None = None,
    source_manifest: str | Path | None = None,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    archive_root: str | Path = DEFAULT_ARCHIVE_ROOT,
    archive_as_of_date: str | date | datetime | None = None,
    artifact_family: str = "snapshots_long",
    max_market_days: int = 60,
    max_rows_per_market_day: int = 250_000,
    batch_rows: int = 65_536,
    outer_min_train_dates: int = 14,
    inner_min_train_dates: int = 7,
    embargo_days: int = 3,
    step_dates: int = 7,
    window_end: str | date | None = None,
    bootstrap_iterations: int = 2_000,
    bootstrap_seed: int = 31_415,
    private_memory_budget_bytes: int = PRODUCTION_PRIVATE_MEMORY_BUDGET_BYTES,
    max_fold_scopes: int = PRODUCTION_MAX_FOLD_SCOPES,
) -> dict[str, Any]:
    """Replay the exact fitted pickle and freeze the four production roles."""

    del archive_root, archive_as_of_date, artifact_family
    if tuple(folders):
        raise ValueError(
            "production qualification consumes the manifest-pinned preselection, not raw folders"
        )
    if not 0 < int(private_memory_budget_bytes) <= 8 * 1024**3:
        raise ValueError("private memory budget must be between 1 byte and 8 GiB")
    if not 0 < int(batch_rows) <= PRODUCTION_MAX_ARROW_BATCH_ROWS:
        raise ValueError(
            f"batch_rows must be between 1 and {PRODUCTION_MAX_ARROW_BATCH_ROWS}"
        )
    if not 0 < int(max_market_days) <= PRODUCTION_MAX_MARKET_DAYS:
        raise ValueError(
            f"max_market_days must be between 1 and {PRODUCTION_MAX_MARKET_DAYS}"
        )
    if not 0 < int(max_rows_per_market_day) <= PRODUCTION_MAX_ROWS_PER_MARKET_DAY:
        raise ValueError(
            "max_rows_per_market_day must be between 1 and "
            f"{PRODUCTION_MAX_ROWS_PER_MARKET_DAY}"
        )
    if not 0 < int(max_fold_scopes) <= PRODUCTION_MAX_FOLD_SCOPES:
        raise ValueError(
            f"max_fold_scopes must be between 1 and {PRODUCTION_MAX_FOLD_SCOPES}"
        )
    for path, label in (
        (model_artifact, "model artifact"),
        (calibration_artifact, "calibration artifact"),
        (routing_artifact, "routing artifact"),
        (preselection_lock, "preselection lock"),
        (replay_manifest, "replay manifest"),
    ):
        if not Path(path).resolve().is_file():
            raise FileNotFoundError(f"production {label} is missing: {path}")

    preselection = verify_production_preselection(
        preselection_lock,
        source_corpus=source_corpus,
        source_manifest=source_manifest,
        replay_manifest=replay_manifest,
        batch_rows=batch_rows,
    )
    if window_end is not None and str(window_end) != preselection["window_lock"][
        "window_end"
    ]:
        raise ContractViolation(
            "invalid_evaluation_window_lock",
            "qualification window end differs from the preselected lock",
        )
    try:
        with Path(model_artifact).resolve().open("rb") as handle:
            model_bundle = pickle.load(handle)
    except (OSError, EOFError, pickle.PickleError) as exc:
        raise ContractViolation(
            "invalid_candidate_model_artifact",
            f"cannot load the exact pooled model artifact: {exc}",
        ) from exc
    if not isinstance(model_bundle, Mapping):
        raise ContractViolation(
            "invalid_candidate_model_artifact", "pooled model artifact is not a mapping"
        )
    try:
        training = verify_pooled_point_in_time_training_evidence(model_bundle)
    except (TypeError, ValueError) as exc:
        raise ContractViolation(
            "invalid_candidate_training_evidence", str(exc)
        ) from exc
    lock_binding = training.get("preselection_lock") or {}
    expected_lock_binding = {
        "preselection_hash": preselection["preselection_hash"],
        "window_lock_id": preselection["window_lock"]["window_lock_id"],
        "selection_universe_sha256": preselection["selection_universe"]["sha256"],
    }
    if any(lock_binding.get(key) != value for key, value in expected_lock_binding.items()):
        raise ContractViolation(
            "candidate_training_preselection_mismatch",
            "serialized trainer evidence is not bound to the exact preselection lock",
        )
    expected_config = {
        "outer_min_train_dates": int(outer_min_train_dates),
        "inner_min_train_dates": int(inner_min_train_dates),
        "outer_validation_dates": 1,
        "inner_validation_dates": 1,
        "embargo_days": int(embargo_days),
        "step_dates": int(step_dates),
    }
    if training.get("fold_config") != expected_config:
        raise ContractViolation(
            "candidate_training_plan_mismatch",
            "qualification fold configuration differs from the fitted artifact",
        )
    if _parse_utc(
        preselection["generated_at_utc"], "preselection.generated_at_utc"
    ) > _parse_utc(training["generated_at_utc"], "training.generated_at_utc"):
        raise ContractViolation(
            "window_locked_after_candidate_selection",
            "training evidence predates the production evaluation lock",
        )

    graph = _candidate_training_graph(
        candidate_id=candidate_id,
        release_id=release_id,
        preselection=preselection,
        training_evidence=training,
        model_artifact=model_artifact,
        calibration_artifact=calibration_artifact,
        routing_artifact=routing_artifact,
    )
    fleet_dates = list(preselection["selection_universe"]["fleet_dates"])
    manifest = _materialize_bounded_candidate_replay(
        candidate_id=candidate_id,
        release_id=release_id,
        corpus_out=corpus_out,
        manifest_out=manifest_out,
        model_artifact=model_artifact,
        preselection_lock=preselection_lock,
        replay_manifest=replay_manifest,
        snapshots_root=snapshots_root,
        fleet_dates=fleet_dates,
        training_graph=graph,
        max_market_days=max_market_days,
        max_rows_per_market_day=max_rows_per_market_day,
        batch_rows=batch_rows,
    )
    replay_universe = selection_universe_contract(corpus_out, batch_rows=batch_rows)
    if replay_universe != preselection["selection_universe"]:
        raise ContractViolation(
            "candidate_replay_population_mismatch",
            "fresh candidate replay differs from the preselected evaluation population",
        )
    corpus_sha = sha256_file(corpus_out)
    observed_dates = collect_parquet_fleet_dates(corpus_out, batch_rows=batch_rows)
    if tuple(fleet_dates) != observed_dates:
        raise ContractViolation(
            "candidate_replay_population_mismatch",
            "candidate replay fleet dates differ from the locked universe",
        )
    lock = dict(preselection["window_lock"])
    scope_count = sum(1 + len(row.get("inner") or ()) for row in training["folds"])
    observed_bounds = manifest["streaming_bounds"]
    resources = {
        "host_physical_memory_bytes": PRODUCTION_HOST_PHYSICAL_MEMORY_BYTES,
        "private_memory_budget_bytes": int(private_memory_budget_bytes),
        "corpus_read_mode": "market_day_streaming",
        "raw_market_days_retained_at_once": 1,
        "max_market_days": int(max_market_days),
        "max_rows_per_market_day": int(max_rows_per_market_day),
        "parquet_batch_rows": int(observed_bounds["arrow_write_batch_rows"]),
        "observed_peak_arrow_rows": int(
            observed_bounds["observed_peak_arrow_rows"]
        ),
        "max_fold_scopes": int(max_fold_scopes),
        "observed_fold_scopes": scope_count,
        "observed_market_days": int(observed_bounds["observed_market_days"]),
        "observed_peak_rows_per_market_day": int(
            observed_bounds["observed_peak_rows_per_market_day"]
        ),
        "replay_artifact_loads_retained_at_once": 1,
    }
    if scope_count > int(max_fold_scopes):
        raise ContractViolation(
            "point_in_time_fold_budget_exceeded",
            f"fitted artifact contains {scope_count} scopes; budget is {max_fold_scopes}",
        )
    plan_kwargs = {
        "outer_min_train_dates": int(outer_min_train_dates),
        "inner_min_train_dates": int(inner_min_train_dates),
        "embargo_days": int(embargo_days),
        "step_dates": int(step_dates),
        "candidate_id": candidate_id,
        "release_id": release_id,
        "corpus_sha256": corpus_sha,
        "materialization_manifest_hash": str(manifest["manifest_hash"]),
        "selection_excluded_dates": lock["target_dates"],
        "selection_window_lock": lock,
        "resource_contract": resources,
    }
    seed_plan = validation_plan_payload(observed_dates, **plan_kwargs)
    if seed_plan["folds"] != training["folds"]:
        raise ContractViolation(
            "candidate_training_plan_mismatch",
            "serialized trainer folds differ from the frozen rolling-origin plan",
        )
    plan = validation_plan_payload(
        observed_dates,
        generated_at_utc=_utc_now_iso(),
        fit_receipts=training["fit_receipts"],
        require_output_bound_receipts=True,
        **plan_kwargs,
    )
    plan.pop("plan_hash", None)
    plan["candidate_training_graph"] = graph
    plan["candidate_training_graph_hash"] = graph["graph_hash"]
    plan = _finalize_hash(plan, "plan_hash")
    verify_validation_plan_payload(
        plan,
        expected_candidate_id=candidate_id,
        expected_release_id=release_id,
        expected_corpus_sha256=corpus_sha,
        expected_manifest_hash=str(manifest["manifest_hash"]),
        expected_fleet_dates=observed_dates,
        require_fit_receipts=True,
    )
    _atomic_write_json(validation_plan_out, plan)
    evaluation = evaluate_point_in_time_parquet(
        corpus_out,
        manifest_path=manifest_out,
        window_days=14,
        window_end=lock["window_end"],
        batch_rows=batch_rows,
        bootstrap_iterations=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
        candidate_id=candidate_id,
        release_id=release_id,
        candidate_artifact_sha256=graph["candidate_artifacts"]["model_sha256"],
        validation_plan_hash=str(plan["plan_hash"]),
        window_lock=lock,
    )
    evaluation.pop("evaluation_hash", None)
    evaluation.setdefault("contract_binding", {}).update(
        {
            "candidate_training_graph_hash": graph["graph_hash"],
            "selection_universe_sha256": replay_universe["sha256"],
        }
    )
    evaluation = _finalize_hash(evaluation, "evaluation_hash")
    _atomic_write_json(evaluation_out, evaluation)

    qualification = verify_production_point_in_time_artifacts(
        corpus_path=corpus_out,
        materialization_manifest_path=manifest_out,
        validation_plan_path=validation_plan_out,
        streaming_evaluation_path=evaluation_out,
        expected_candidate_id=candidate_id,
        expected_release_id=release_id,
        expected_candidate_artifact_sha256=graph["candidate_artifacts"][
            "model_sha256"
        ],
        expected_calibration_artifact_sha256=graph["candidate_artifacts"][
            "calibration_sha256"
        ],
        expected_routing_artifact_sha256=graph["candidate_artifacts"][
            "routing_sha256"
        ],
        expected_route_selection=graph["route_selection"],
    )
    return {
        "status": "PASS",
        "candidate_id": candidate_id,
        "release_id": release_id,
        "artifacts": {
            "point_in_time_corpus": str(corpus_out),
            "point_in_time_materialization_manifest": str(manifest_out),
            "point_in_time_validation_plan": str(validation_plan_out),
            "point_in_time_streaming_evaluation": str(evaluation_out),
        },
        "window_lock": lock,
        "candidate_training_graph": graph,
        "resource_contract": resources,
        "qualification": qualification,
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


def _prepare_replay_manifest(
    *,
    source_manifest: str | Path,
    source_replay_manifest: str | Path | None,
    replay_manifest_out: str | Path,
    snapshots_root: str | Path,
    as_of: str | None,
    quality_grades: str,
) -> Path:
    output = Path(replay_manifest_out).resolve()
    copy_source: Path | None = None
    copy_bytes: bytes | None = None
    if source_replay_manifest:
        source = Path(source_replay_manifest).resolve()
        _load_production_replay_manifest(source)
        copy_source = source
        copy_bytes = _read_bounded_contract_bytes(
            source,
            code="invalid_candidate_replay_manifest",
            max_bytes=PRODUCTION_MAX_REPLAY_MANIFEST_BYTES,
        )
    else:
        source_payload = _read_bounded_contract_json(
            source_manifest,
            code="invalid_materialization_manifest",
            max_bytes=PRODUCTION_MAX_SOURCE_MANIFEST_BYTES,
        )
        if (
            source_payload.get("artifact_type")
            == "production_point_in_time_preselection_source_manifest"
        ):
            binding = source_payload.get("source_replay_manifest") or {}
            source = Path(str(binding.get("path") or "")).resolve()
            copy_source = source
            copy_bytes = _read_bounded_contract_bytes(
                source,
                code="invalid_candidate_replay_manifest",
                max_bytes=PRODUCTION_MAX_REPLAY_MANIFEST_BYTES,
            )
            replay = _load_production_replay_manifest(source)
            if (
                hashlib.sha256(copy_bytes).hexdigest() != binding.get("sha256")
                or replay.get("corpus_hash") != binding.get("corpus_hash")
            ):
                raise ContractViolation(
                    "preselection_source_replay_mismatch",
                    "staged preselection source replay binding is invalid",
                )
        else:
            raise ContractViolation(
                "candidate_dependent_preselection_source",
                "production preselection rejects the generic materialization schema",
            )
    if copy_source is not None:
        if copy_source != output:
            output.parent.mkdir(parents=True, exist_ok=True)
            temp = output.with_name(f".{output.name}.{os.getpid()}.tmp")
            temp.write_bytes(copy_bytes or b"")
            os.replace(temp, output)
    else:  # pragma: no cover - every accepted production source is byte-copied
        raise ContractViolation(
            "invalid_candidate_replay_manifest",
            "production replay manifest source is missing",
        )
    _load_production_replay_manifest(output)
    return output


def _cmd_prelock(args: argparse.Namespace) -> None:
    if (
        not 0 < int(args.batch_rows) <= PRODUCTION_MAX_ARROW_BATCH_ROWS
        or not 0 < int(args.max_market_days) <= PRODUCTION_MAX_MARKET_DAYS
        or not 0
        < int(args.max_rows_per_market_day)
        <= PRODUCTION_MAX_ROWS_PER_MARKET_DAY
    ):
        raise SystemExit("production preselection bounds exceed the reviewed maximum")
    source_corpus = args.source_corpus
    source_manifest = args.source_manifest
    if bool(source_corpus) != bool(source_manifest):
        raise SystemExit("--source-corpus and --source-manifest must be supplied together")
    if source_corpus and args.folder:
        raise SystemExit("staged source corpus cannot be combined with --folder")
    if not source_corpus:
        if not args.folder:
            raise SystemExit("preselection requires a staged source or explicit folders")
        if len(args.folder) > int(args.max_market_days):
            raise SystemExit("explicit folders exceed the production market-day bound")
        if not args.source_corpus_out or not args.source_manifest_out:
            raise SystemExit("folder materialization requires source output paths")
        grades = tuple(
            value.strip()
            for value in str(args.quality_grades).split(",")
            if value.strip()
        )
        built_replay = build_promotion_corpus(
            folders=[Path(item) for item in args.folder],
            snapshots_root=args.snapshots_root,
            as_of=args.as_of or None,
            quality_grades=grades or None,
            admit_promotion_countable=False,
            input_loader=lambda folder: load_bounded_preselection_folder_inputs(
                folder,
                snapshots_root=args.snapshots_root,
                max_rows_per_market_day=args.max_rows_per_market_day,
            ),
            max_manifest_bytes=PRODUCTION_MAX_REPLAY_MANIFEST_BYTES,
        )
        if args.source_replay_manifest:
            supplied_path = Path(args.source_replay_manifest).resolve()
            supplied_replay = _load_production_replay_manifest(supplied_path)
            if supplied_replay.get("corpus_hash") != built_replay.get("corpus_hash"):
                raise ContractViolation(
                    "candidate_replay_manifest_population_mismatch",
                    "explicit folders differ from the supplied replay manifest",
                )
            replay_payload = _read_contract_json(
                supplied_path,
                code="invalid_candidate_replay_manifest",
            )
        else:
            replay_payload = built_replay
        _atomic_write_json(args.replay_manifest_out, replay_payload)
        replay_manifest = Path(args.replay_manifest_out).resolve()
        _load_production_replay_manifest(replay_manifest)
        manifest = materialize_production_preselection_source(
            replay_manifest=replay_manifest,
            parquet_out=args.source_corpus_out,
            manifest_out=args.source_manifest_out,
            snapshots_root=args.snapshots_root,
            max_market_days=args.max_market_days,
            max_rows_per_market_day=args.max_rows_per_market_day,
            batch_rows=args.batch_rows,
        )
        if manifest.get("status") != "PASS":
            raise SystemExit("candidate-independent source materialization did not pass")
        source_corpus = args.source_corpus_out
        source_manifest = args.source_manifest_out
    else:
        replay_manifest = _prepare_replay_manifest(
            source_manifest=source_manifest,
            source_replay_manifest=args.source_replay_manifest or None,
            replay_manifest_out=args.replay_manifest_out,
            snapshots_root=args.snapshots_root,
            as_of=args.as_of or None,
            quality_grades=args.quality_grades,
        )
    payload = prepare_production_preselection(
        source_corpus=source_corpus,
        source_manifest=source_manifest,
        replay_manifest=replay_manifest,
        lock_out=args.lock_out,
        window_end=args.window_end or None,
        batch_rows=args.batch_rows,
        max_market_days=args.max_market_days,
        max_rows_per_market_day=args.max_rows_per_market_day,
    )
    print(
        "point-in-time production preselection: "
        f"status={payload['status']} lock={payload['window_lock']['window_lock_id']}"
    )


def _cmd_qualify(args: argparse.Namespace) -> None:
    payload = materialize_production_candidate_packet(
        candidate_id=args.candidate_id,
        release_id=args.release_id or args.candidate_id,
        corpus_out=args.corpus_out,
        manifest_out=args.manifest_out,
        validation_plan_out=args.validation_plan_out,
        evaluation_out=args.evaluation_out,
        model_artifact=args.model_artifact,
        calibration_artifact=args.calibration_artifact,
        routing_artifact=args.routing_artifact,
        preselection_lock=args.preselection_lock,
        replay_manifest=args.replay_manifest,
        folders=[Path(item) for item in args.folder],
        source_corpus=args.source_corpus or None,
        source_manifest=args.source_manifest or None,
        snapshots_root=args.snapshots_root,
        archive_root=args.archive_root,
        archive_as_of_date=args.as_of or None,
        artifact_family=args.artifact_family,
        max_market_days=args.max_market_days,
        max_rows_per_market_day=args.max_rows_per_market_day,
        batch_rows=args.batch_rows,
        outer_min_train_dates=args.outer_min_train_dates,
        inner_min_train_dates=args.inner_min_train_dates,
        embargo_days=args.embargo_days,
        step_dates=args.step_dates,
        window_end=args.window_end or None,
        bootstrap_iterations=args.bootstrap_iterations,
        bootstrap_seed=args.bootstrap_seed,
        private_memory_budget_bytes=args.private_memory_budget_bytes,
        max_fold_scopes=args.max_fold_scopes,
    )
    print(
        "point-in-time production qualification: "
        f"status={payload['status']} candidate={payload['candidate_id']} "
        f"receipts={payload['qualification']['fit_receipt_count']}"
    )


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

    prelock = subparsers.add_parser(
        "prelock-production",
        help="freeze a candidate-independent 14-day window before training",
    )
    prelock.add_argument("--folder", action="append", default=[])
    prelock.add_argument("--source-corpus", default="")
    prelock.add_argument("--source-manifest", default="")
    prelock.add_argument("--source-corpus-out", default="")
    prelock.add_argument("--source-manifest-out", default="")
    prelock.add_argument("--source-replay-manifest", default="")
    prelock.add_argument("--replay-manifest-out", required=True)
    prelock.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    prelock.add_argument("--archive-root", default=str(DEFAULT_ARCHIVE_ROOT))
    prelock.add_argument("--as-of", default="")
    prelock.add_argument("--artifact-family", default="snapshots_long")
    prelock.add_argument("--quality-grades", default="complete,manual_override")
    prelock.add_argument("--window-end", default="")
    prelock.add_argument("--max-market-days", type=int, default=60)
    prelock.add_argument("--max-rows-per-market-day", type=int, default=250_000)
    prelock.add_argument("--batch-rows", type=int, default=65_536)
    prelock.add_argument("--lock-out", required=True)
    prelock.set_defaults(func=_cmd_prelock)

    qualify = subparsers.add_parser(
        "qualify-production",
        help="materialize and verify all four production candidate PIT roles",
    )
    qualify.add_argument("--candidate-id", required=True)
    qualify.add_argument("--release-id", default="")
    qualify.add_argument("--folder", action="append", default=[])
    qualify.add_argument("--source-corpus", default="")
    qualify.add_argument("--source-manifest", default="")
    qualify.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    qualify.add_argument("--archive-root", default=str(DEFAULT_ARCHIVE_ROOT))
    qualify.add_argument("--as-of", default="")
    qualify.add_argument("--artifact-family", default="snapshots_long")
    qualify.add_argument("--model-artifact", required=True)
    qualify.add_argument("--calibration-artifact", required=True)
    qualify.add_argument("--routing-artifact", required=True)
    qualify.add_argument("--preselection-lock", required=True)
    qualify.add_argument("--replay-manifest", required=True)
    qualify.add_argument("--corpus-out", required=True)
    qualify.add_argument("--manifest-out", required=True)
    qualify.add_argument("--validation-plan-out", required=True)
    qualify.add_argument("--evaluation-out", required=True)
    qualify.add_argument("--max-market-days", type=int, default=60)
    qualify.add_argument("--max-rows-per-market-day", type=int, default=250_000)
    qualify.add_argument("--batch-rows", type=int, default=65_536)
    qualify.add_argument("--outer-min-train-dates", type=int, default=14)
    qualify.add_argument("--inner-min-train-dates", type=int, default=7)
    qualify.add_argument("--embargo-days", type=int, choices=range(3, 8), default=3)
    qualify.add_argument("--step-dates", type=int, default=7)
    qualify.add_argument("--max-fold-scopes", type=int, default=128)
    qualify.add_argument("--window-end", default="")
    qualify.add_argument("--bootstrap-iterations", type=int, default=2_000)
    qualify.add_argument("--bootstrap-seed", type=int, default=31_415)
    qualify.add_argument(
        "--private-memory-budget-bytes",
        type=int,
        default=PRODUCTION_PRIVATE_MEMORY_BUDGET_BYTES,
    )
    qualify.set_defaults(func=_cmd_qualify)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
