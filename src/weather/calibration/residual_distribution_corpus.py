"""Point-in-time corpus materialization for ``ResidualDistributionV1``.

The legacy pooled trainers rebuild historical feature rows from daily files.
That path cannot prove which provider payload was available at prediction time
and fills several missing values with healthy-looking defaults.  This module
instead consumes the captured ``replay_inputs.jsonl`` payload, selects exactly
one declared checkpoint per market/date/cutoff, and joins settlement only after
the point-in-time feature context has been built.

The materializer is deliberately independent of model fitting.  A caller may
inject a feature builder for tests; the default builder runs the same pure
``ResidualDistributionV1`` canonicalizer used by live shadow inference.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from weather.experiment_contract import canonical_json, finalize_self_hash
from weather.backtesting.settled_days import discover_settled_folders, folder_market_id
from weather.market.market_registry import REGISTRY
from weather.model.continuous_density import native_to_f
from weather.model.feature_store import FEATURE_SCHEMA_VERSION
from weather.model.model_constants import INTRADAY_CUTOFF_HOURS
from weather.operations.closed_market_day_archive import DEFAULT_SNAPSHOTS_ROOT
from weather.paths import data_path


CORPUS_SCHEMA_VERSION = "residual_distribution_training_corpus_v1"
MANIFEST_SCHEMA_VERSION = "residual_distribution_training_corpus_manifest_v1"
DEFAULT_MAX_CHECKPOINT_LATENESS_MINUTES = 15
REPLAY_INPUT_FILENAME = "replay_inputs.jsonl"
SETTLEMENT_FILENAME = "settlement.json"
SNAPSHOTS_LONG_FILENAME = "snapshots_long.csv"
FORBIDDEN_FEATURE_TOKENS = (
    "settlement",
    "winning_band",
    "outcome",
    "label",
    "final_high",
    "final_bucket",
    "market_yes",
    "market_no",
    "edge",
)


class ResidualCorpusError(ValueError):
    """A source row cannot enter the point-in-time training corpus."""


def _parse_timestamp(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ResidualCorpusError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ResidualCorpusError(f"{field} must include a timezone")
    return parsed


def _parse_date(value: Any, field: str = "target_date") -> date:
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError as exc:
        raise ResidualCorpusError(f"{field} must be an ISO date") from exc


def _finite(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _json_safe(value: Any) -> Any:
    """Replace model-native NaN/Inf sentinels with explicit JSON nulls."""

    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def replay_input_sha256(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(_json_safe(dict(row))).encode("utf-8")).hexdigest()


def checkpoint_lateness_minutes(
    row: Mapping[str, Any],
    *,
    target_date: str | date,
    cutoff_hour: int,
) -> float:
    """Return minutes from the declared cutoff to the captured prediction.

    Checkpoints are the first capture at or after the wall-clock cutoff.  A
    negative value is therefore a pre-cutoff row and is never eligible.
    """

    captured = _parse_timestamp(
        row.get("captured_at_local") or row.get("built_at"),
        "captured_at_local",
    )
    expected_date = target_date if isinstance(target_date, date) else _parse_date(target_date)
    if captured.date() != expected_date:
        raise ResidualCorpusError(
            f"captured date {captured.date().isoformat()} does not match target date "
            f"{expected_date.isoformat()}"
        )
    cutoff = captured.replace(
        hour=int(cutoff_hour),
        minute=0,
        second=0,
        microsecond=0,
    )
    return (captured - cutoff).total_seconds() / 60.0


def collapse_to_predeclared_checkpoints(
    rows: Iterable[Mapping[str, Any]],
    *,
    target_date: str | date,
    cutoff_hours: Sequence[int] = INTRADAY_CUTOFF_HOURS,
    max_lateness_minutes: int = DEFAULT_MAX_CHECKPOINT_LATENESS_MINUTES,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Select one earliest nonnegative capture for every declared cutoff."""

    max_lateness = int(max_lateness_minutes)
    if max_lateness < 0:
        raise ValueError("max_lateness_minutes must be non-negative")
    materialized = [dict(row) for row in rows]
    selected: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for raw_hour in cutoff_hours:
        hour = int(raw_hour)
        eligible: list[tuple[float, str, dict[str, Any]]] = []
        invalid_count = 0
        for row in materialized:
            try:
                lateness = checkpoint_lateness_minutes(
                    row,
                    target_date=target_date,
                    cutoff_hour=hour,
                )
            except ResidualCorpusError:
                invalid_count += 1
                continue
            if 0.0 <= lateness <= max_lateness:
                eligible.append((lateness, str(row.get("snapshot_id") or ""), row))
        if not eligible:
            exclusions.append({
                "cutoff_hour": hour,
                "reason": "checkpoint_missing",
                "max_lateness_minutes": max_lateness,
                "invalid_timestamp_rows": invalid_count,
            })
            continue
        lateness, _snapshot_id, chosen = min(eligible, key=lambda item: (item[0], item[1]))
        chosen = dict(chosen)
        chosen["_captured_replay_input_sha256"] = replay_input_sha256(chosen)
        chosen["cutoff_hour"] = hour
        chosen["checkpoint_lateness_minutes"] = round(float(lateness), 6)
        selected.append(chosen)
    return selected, exclusions


def read_jsonl(path: str | Path) -> Iterable[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ResidualCorpusError(
                    f"{path}:{line_number} contains invalid JSON"
                ) from exc
            if not isinstance(payload, dict):
                raise ResidualCorpusError(f"{path}:{line_number} must be a JSON object")
            yield payload


def _status_from_source_item(item: Mapping[str, Any]) -> str:
    status = str(item.get("status") or "").strip().lower()
    if status:
        return status
    if bool(item.get("stale")):
        return "stale_cache"
    if bool(item.get("ok")):
        return "fresh"
    return "unknown"


def source_diagnostics_from_replay(
    sources: Mapping[str, Any] | None,
    *,
    captured_at: datetime,
) -> list[dict[str, Any]]:
    """Canonicalize raw replay source envelopes without inventing freshness."""

    diagnostics: list[dict[str, Any]] = []
    for name, raw_item in sorted((sources or {}).items()):
        item = raw_item if isinstance(raw_item, Mapping) else {}
        raw_age = item.get("cache_age_minutes")
        if raw_age is None:
            raw_age = item.get("age_minutes")
        age = _finite(raw_age)
        if age is None and item.get("fetched_at"):
            try:
                fetched = _parse_timestamp(item.get("fetched_at"), f"sources.{name}.fetched_at")
                age = max(
                    0.0,
                    (captured_at.astimezone(timezone.utc) - fetched.astimezone(timezone.utc)).total_seconds()
                    / 60.0,
                )
            except ResidualCorpusError:
                age = None
        diagnostics.append({
            "source": str(name),
            "source_family": item.get("source_family") or str(name),
            "status": _status_from_source_item(item),
            "age_minutes": age,
            "ttl_minutes": _finite(item.get("ttl_minutes")),
            "degradation_state": item.get("degradation_state"),
            "cache_status": item.get("cache_status"),
            "physical_validity_status": item.get("physical_validity_status"),
        })
    return diagnostics


def complete_band_definition(path: str | Path) -> list[dict[str, Any]]:
    """Read one ordered, complete market partition from a snapshot tape."""

    path = Path(path)
    if not path.exists():
        raise ResidualCorpusError(f"market band tape is missing: {path}")
    first_snapshot: str | None = None
    bands: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            snapshot_id = str(row.get("snapshot_id") or "")
            if first_snapshot is None:
                first_snapshot = snapshot_id
            if snapshot_id != first_snapshot:
                break
            value = _finite(row.get("bin_value_c"))
            value_hi = _finite(row.get("bin_value_hi_c"))
            if value is None:
                continue
            bands.append({
                "kind": str(row.get("bin_kind") or "eq"),
                "value": value,
                "value_hi": value if value_hi is None else value_hi,
                "label": str(row.get("range_label") or ""),
            })
    if not bands:
        raise ResidualCorpusError(f"market band tape has no usable partition: {path}")
    return bands


def _default_feature_builder(
    replay_row: Mapping[str, Any],
    *,
    market_id: str,
    unit: str,
    cutoff_hour: int,
) -> dict[str, Any]:
    """Rebuild the shared V1 context from the captured source envelope."""

    from weather.model.residual_distribution_v1 import (
        canonical_candidate_features,
        default_feature_contract,
    )
    from weather.model.toronto_model import TorontoHighTempModel

    captured = _parse_timestamp(
        replay_row.get("captured_at_local") or replay_row.get("built_at"),
        "captured_at_local",
    )
    model = TorontoHighTempModel(
        market_id=market_id,
        target_date=_parse_date(replay_row.get("target_date")),
    )
    sources = replay_row.get("sources") or {}
    vector = model.extract_live_features(sources, int(cutoff_hour), now=captured)
    diagnostics = model.source_diagnostics(sources)
    feature_schema_version = str(vector.get("feature_schema_version") or "").strip()
    contract = default_feature_contract(feature_schema_version)
    context = canonical_candidate_features(
        artifact=contract,
        feature_vector=vector,
        source_diagnostics=diagnostics,
        market_id=market_id,
        unit=unit,
    )
    if isinstance(context, Mapping) and context.get("status") in {"skipped", "failed"}:
        raise ResidualCorpusError(
            f"feature builder rejected checkpoint: {context.get('failure_reason')}: "
            f"{context.get('failure_detail')}"
        )
    output = _json_safe(dict(context))
    output["_feature_schema_version"] = feature_schema_version
    return output


def _feature_anchor_f(features: Mapping[str, Any]) -> float | None:
    for key in ("forecast_high_f", "nwp_anchor_f", "anchor_f", "forecast_high"):
        value = _finite(features.get(key))
        if value is not None:
            return value
    return None


def validate_residual_training_row(row: Mapping[str, Any]) -> dict[str, Any]:
    required_text = (
        "target_date",
        "market_id",
        "snapshot_id",
        "captured_at_utc",
        "captured_at_local",
        "native_unit",
        "feature_schema_version",
        "replay_input_sha256",
        "settlement_sha256",
        "feature_sha256",
    )
    for field in required_text:
        if not str(row.get(field) or "").strip():
            raise ResidualCorpusError(f"training row is missing {field}")
    _parse_date(row.get("target_date"))
    _parse_timestamp(row.get("captured_at_utc"), "captured_at_utc")
    _parse_timestamp(row.get("captured_at_local"), "captured_at_local")
    if int(row.get("cutoff_hour")) not in range(0, 24):
        raise ResidualCorpusError("cutoff_hour must be between 0 and 23")
    for field in ("settlement_high_f", "forecast_anchor_f", "residual_target_f"):
        if _finite(row.get(field)) is None:
            raise ResidualCorpusError(f"training row has non-finite {field}")
    features = row.get("features")
    if not isinstance(features, Mapping) or not features:
        raise ResidualCorpusError("training row features must be a non-empty object")
    forbidden = [
        name
        for name in features
        if any(token in str(name).lower() for token in FORBIDDEN_FEATURE_TOKENS)
    ]
    if forbidden:
        raise ResidualCorpusError(
            "training features contain outcome/market-derived fields: " + ", ".join(sorted(forbidden))
        )
    expected_feature_hash = hashlib.sha256(
        canonical_json(dict(features)).encode("utf-8")
    ).hexdigest()
    if row.get("feature_sha256") != expected_feature_hash:
        raise ResidualCorpusError("feature_sha256 does not match the feature payload")
    bands = row.get("market_bands")
    if not isinstance(bands, list) or len(bands) < 2:
        raise ResidualCorpusError("training row requires a complete market-band partition")
    return dict(row)


def materialize_market_day_rows(
    folder: str | Path,
    *,
    cutoff_hours: Sequence[int] = INTRADAY_CUTOFF_HOURS,
    max_lateness_minutes: int = DEFAULT_MAX_CHECKPOINT_LATENESS_MINUTES,
    require_countable_settlement: bool = True,
    feature_builder: Callable[..., Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    folder = Path(folder)
    settlement_path = folder / SETTLEMENT_FILENAME
    replay_path = folder / REPLAY_INPUT_FILENAME
    if not settlement_path.exists() or not replay_path.exists():
        return [], [{
            "folder": str(folder),
            "reason": "missing_settlement_or_replay_input",
        }]
    settlement = json.loads(settlement_path.read_text(encoding="utf-8"))
    if require_countable_settlement and not bool(settlement.get("promotion_countable")):
        return [], [{
            "folder": str(folder),
            "reason": "settlement_not_promotion_countable",
        }]
    market_id = str(settlement.get("market_id") or "").strip()
    spec = REGISTRY.get(market_id)
    if spec is None:
        return [], [{"folder": str(folder), "reason": "unknown_market"}]
    unit = str(settlement.get("settlement_unit") or spec.display_unit).upper()
    if unit != str(spec.display_unit).upper():
        return [], [{"folder": str(folder), "reason": "settlement_unit_mismatch"}]
    target_date = str(settlement.get("target_date") or "")
    settlement_high_native = _finite(settlement.get("settlement_high"))
    if not target_date or settlement_high_native is None:
        return [], [{"folder": str(folder), "reason": "missing_settlement_target"}]
    settlement_high_f = native_to_f(settlement_high_native, unit)
    bands = complete_band_definition(folder / SNAPSHOTS_LONG_FILENAME)
    selected, exclusions = collapse_to_predeclared_checkpoints(
        read_jsonl(replay_path),
        target_date=target_date,
        cutoff_hours=cutoff_hours,
        max_lateness_minutes=max_lateness_minutes,
    )
    output: list[dict[str, Any]] = []
    builder = feature_builder or _default_feature_builder
    settlement_hash = sha256_file(settlement_path)
    replay_file_hash = sha256_file(replay_path)
    for selected_row in selected:
        cutoff_hour = int(selected_row["cutoff_hour"])
        try:
            features = _json_safe(dict(builder(
                selected_row,
                market_id=market_id,
                unit=unit,
                cutoff_hour=cutoff_hour,
            )))
            feature_schema_version = str(
                features.pop("_feature_schema_version", None)
                or selected_row.get("feature_schema_version")
                or FEATURE_SCHEMA_VERSION
            )
            anchor_f = _feature_anchor_f(features)
            if anchor_f is None:
                raise ResidualCorpusError("canonical feature context has no forecast anchor")
            feature_hash = hashlib.sha256(
                canonical_json(features).encode("utf-8")
            ).hexdigest()
            row = {
                "schema_version": CORPUS_SCHEMA_VERSION,
                "target_date": target_date,
                "market_id": market_id,
                "snapshot_id": str(selected_row.get("snapshot_id") or ""),
                "cutoff_hour": cutoff_hour,
                "checkpoint_lateness_minutes": selected_row["checkpoint_lateness_minutes"],
                "captured_at_utc": str(selected_row.get("captured_at_utc") or ""),
                "captured_at_local": str(selected_row.get("captured_at_local") or ""),
                "built_at": str(selected_row.get("built_at") or ""),
                "native_unit": unit,
                "feature_schema_version": feature_schema_version,
                "settlement_high_f": float(settlement_high_f),
                "forecast_anchor_f": float(anchor_f),
                "residual_target_f": float(settlement_high_f - anchor_f),
                "features": features,
                "feature_sha256": feature_hash,
                "source_health": source_diagnostics_from_replay(
                    selected_row.get("sources") or {},
                    captured_at=_parse_timestamp(
                        selected_row.get("captured_at_local") or selected_row.get("built_at"),
                        "captured_at_local",
                    ),
                ),
                "market_bands": bands,
                "winning_band": {
                    "kind": settlement.get("winning_band_kind"),
                    "value": settlement.get("winning_band_value"),
                    "value_hi": settlement.get("winning_band_value_hi"),
                },
                "settlement_quality": settlement.get("quality_grade"),
                "settlement_countable": bool(settlement.get("promotion_countable")),
                "release_id": str(
                    selected_row.get("release_id")
                    or (selected_row.get("model_identity") or {}).get("release_id")
                    or ""
                ),
                "replay_input_sha256": selected_row["_captured_replay_input_sha256"],
                "replay_file_sha256": replay_file_hash,
                "settlement_sha256": settlement_hash,
                "runtime_identity": selected_row.get("runtime_identity") or {},
                "model_identity": selected_row.get("model_identity") or {},
            }
            row["training_evidence_class"] = (
                "release_bound" if row["release_id"] else "research_only"
            )
            row["promotion_training_countable"] = bool(
                row["settlement_countable"] and row["release_id"]
            )
            output.append(validate_residual_training_row(_json_safe(row)))
        except (ResidualCorpusError, TypeError, ValueError) as exc:
            exclusions.append({
                "folder": str(folder),
                "market_id": market_id,
                "target_date": target_date,
                "cutoff_hour": cutoff_hour,
                "snapshot_id": selected_row.get("snapshot_id"),
                "reason": "checkpoint_rejected",
                "detail": str(exc),
            })
    for exclusion in exclusions:
        exclusion.setdefault("folder", str(folder))
        exclusion.setdefault("market_id", market_id)
        exclusion.setdefault("target_date", target_date)
    return output, exclusions


def materialize_residual_training_corpus(
    folders: Iterable[str | Path],
    *,
    cutoff_hours: Sequence[int] = INTRADAY_CUTOFF_HOURS,
    max_lateness_minutes: int = DEFAULT_MAX_CHECKPOINT_LATENESS_MINUTES,
    require_countable_settlement: bool = True,
    feature_builder: Callable[..., Mapping[str, Any]] | None = None,
    corpus_out: str | Path | None = None,
    manifest_out: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Materialize a self-hashed, one-row-per-checkpoint training corpus."""

    rows: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []
    for raw_folder in sorted({str(Path(value).resolve()) for value in folders}):
        folder = Path(raw_folder)
        market_rows, market_exclusions = materialize_market_day_rows(
            folder,
            cutoff_hours=cutoff_hours,
            max_lateness_minutes=max_lateness_minutes,
            require_countable_settlement=require_countable_settlement,
            feature_builder=feature_builder,
        )
        rows.extend(market_rows)
        exclusions.extend(market_exclusions)
        inputs.append({
            "folder": str(folder),
            "replay_input_sha256": (
                sha256_file(folder / REPLAY_INPUT_FILENAME)
                if (folder / REPLAY_INPUT_FILENAME).exists()
                else None
            ),
            "settlement_sha256": (
                sha256_file(folder / SETTLEMENT_FILENAME)
                if (folder / SETTLEMENT_FILENAME).exists()
                else None
            ),
        })
    rows.sort(key=lambda row: (
        row["target_date"],
        row["market_id"],
        int(row["cutoff_hour"]),
    ))
    identities = [
        (row["target_date"], row["market_id"], int(row["cutoff_hour"]))
        for row in rows
    ]
    if len(identities) != len(set(identities)):
        raise ResidualCorpusError("corpus contains duplicate market/date/cutoff rows")
    corpus_hash = hashlib.sha256(
        canonical_json(rows).encode("utf-8")
    ).hexdigest()
    manifest = finalize_self_hash({
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "artifact_type": "residual_distribution_training_corpus_manifest",
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "corpus_schema_version": CORPUS_SCHEMA_VERSION,
        "corpus_sha256": corpus_hash,
        "selection_policy": {
            "checkpoint": "earliest_capture_at_or_after_cutoff",
            "cutoff_hours": [int(hour) for hour in cutoff_hours],
            "max_lateness_minutes": int(max_lateness_minutes),
            "substitution_allowed": False,
        },
        "label_policy": {
            "require_countable_settlement": bool(require_countable_settlement),
            "join_after_feature_construction": True,
        },
        "counts": {
            "input_market_days": len(inputs),
            "accepted_rows": len(rows),
            "excluded_rows": len(exclusions),
            "fleet_dates": len({row["target_date"] for row in rows}),
            "market_days": len({(row["target_date"], row["market_id"]) for row in rows}),
            "release_bound_rows": sum(
                1 for row in rows if row.get("training_evidence_class") == "release_bound"
            ),
            "research_only_rows": sum(
                1 for row in rows if row.get("training_evidence_class") == "research_only"
            ),
        },
        "inputs": inputs,
        "exclusions": exclusions,
    }, hash_field="manifest_sha256")
    if corpus_out is not None:
        _atomic_write_jsonl(corpus_out, rows)
    if manifest_out is not None:
        _atomic_write_json(manifest_out, manifest)
    return rows, manifest


def verify_residual_corpus_manifest(
    rows: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ResidualCorpusError("residual corpus manifest schema mismatch")
    expected_manifest = finalize_self_hash(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"},
        hash_field="manifest_sha256",
    )
    if manifest.get("manifest_sha256") != expected_manifest.get("manifest_sha256"):
        raise ResidualCorpusError("residual corpus manifest self-hash mismatch")
    validated = [validate_residual_training_row(row) for row in rows]
    corpus_hash = hashlib.sha256(canonical_json(validated).encode("utf-8")).hexdigest()
    if manifest.get("corpus_sha256") != corpus_hash:
        raise ResidualCorpusError("residual corpus hash mismatch")
    return dict(manifest)


def _atomic_write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _atomic_write_jsonl(path: str | Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(canonical_json(dict(row)) + "\n")
    os.replace(temporary, path)


def _parse_cutoff_hours(value: str) -> tuple[int, ...]:
    hours = tuple(int(item.strip()) for item in str(value).split(",") if item.strip())
    if not hours or any(hour not in range(24) for hour in hours) or len(set(hours)) != len(hours):
        raise argparse.ArgumentTypeError("cutoff hours must be unique integers from 0 through 23")
    return hours


def _newest_per_market(folders: Sequence[Path], limit: int) -> list[Path]:
    if int(limit) <= 0:
        return list(folders)
    by_market: dict[str, list[Path]] = {}
    for folder in folders:
        by_market.setdefault(str(folder_market_id(folder) or "unknown"), []).append(folder)
    return sorted(
        folder
        for market_folders in by_market.values()
        for folder in market_folders[-int(limit):]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize a hash-linked ResidualDistributionV1 PIT training corpus."
    )
    parser.add_argument("--folder", action="append", default=[])
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--as-of", default="")
    parser.add_argument("--market-id", default="")
    parser.add_argument(
        "--cutoff-hours",
        type=_parse_cutoff_hours,
        default=tuple(INTRADAY_CUTOFF_HOURS),
    )
    parser.add_argument(
        "--max-market-days-per-market",
        type=int,
        default=0,
        help="Bounded research/smoke cap; zero consumes every discovered settled day.",
    )
    parser.add_argument(
        "--max-lateness-minutes",
        type=int,
        default=DEFAULT_MAX_CHECKPOINT_LATENESS_MINUTES,
    )
    parser.add_argument(
        "--allow-noncountable-settlement",
        action="store_true",
        help="Research-only: retain labels that are not promotion-countable.",
    )
    parser.add_argument(
        "--out",
        default=str(data_path("backtest", "residual_distribution_v1_training_corpus.jsonl")),
    )
    parser.add_argument(
        "--manifest-out",
        default=str(data_path("backtest", "residual_distribution_v1_training_corpus_manifest.json")),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    folders = [Path(value) for value in args.folder]
    if not folders:
        folders = discover_settled_folders(
            root=args.snapshots_root,
            as_of=args.as_of or None,
            required_file=REPLAY_INPUT_FILENAME,
            market_id=args.market_id or None,
        )
    folders = _newest_per_market(folders, args.max_market_days_per_market)
    rows, manifest = materialize_residual_training_corpus(
        folders,
        cutoff_hours=args.cutoff_hours,
        max_lateness_minutes=args.max_lateness_minutes,
        require_countable_settlement=not args.allow_noncountable_settlement,
        corpus_out=args.out,
        manifest_out=args.manifest_out,
    )
    print(
        "ResidualDistributionV1 corpus: "
        f"rows={len(rows)} excluded={manifest['counts']['excluded_rows']} "
        f"fleet_dates={manifest['counts']['fleet_dates']} out={args.out}"
    )


__all__ = [name for name in globals() if not name.startswith("_")]


if __name__ == "__main__":
    main()
