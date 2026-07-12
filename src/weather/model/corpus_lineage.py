"""Deterministic training/evaluation corpus lineage for model bundles."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from weather.model.feature_safety import is_forbidden_label_outcome_field
from weather.schema_registry import schema_version


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(child) for key, child in sorted(value.items(), key=lambda row: str(row[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_value(child) for child in value]
    if hasattr(value, "item"):
        try:
            return _json_value(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _target_date(row: Mapping[str, Any]) -> str | None:
    for key in ("target_date", "local_date", "date"):
        value = row.get(key)
        if value in (None, ""):
            continue
        try:
            parsed = date.fromisoformat(str(value)[:10])
        except ValueError:
            continue
        return parsed.isoformat()
    return None


def _partition(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    row_hashes: list[str] = []
    dates: list[str] = []
    for row in rows:
        normalized = _json_value(row)
        encoded = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        row_hashes.append(hashlib.sha256(encoded).hexdigest())
        target_date = _target_date(row)
        if target_date:
            dates.append(target_date)
    digest = hashlib.sha256()
    for row_hash in sorted(row_hashes):
        digest.update(row_hash.encode("ascii"))
        digest.update(b"\n")
    return {
        "row_count": len(row_hashes),
        "sha256": digest.hexdigest(),
        "target_date_min": min(dates) if dates else None,
        "target_date_max": max(dates) if dates else None,
        "target_date_count": len(set(dates)),
    }


def build_pooled_corpus_lineage(
    rows: Iterable[Mapping[str, Any]],
    *,
    holdout_year: int | None,
    model_input_fields: Iterable[str],
) -> dict[str, Any]:
    """Attest selection-train, evaluation, and final-refit row partitions."""

    records = list(rows)
    if holdout_year is None:
        selection = records
        evaluation: list[Mapping[str, Any]] = []
    else:
        selection = [row for row in records if int(row.get("year") or 0) != int(holdout_year)]
        evaluation = [row for row in records if int(row.get("year") or 0) == int(holdout_year)]
    all_fields = sorted({str(key) for row in records for key in row})
    partition_metadata = {"date", "local_date", "market_id", "target_date", "year"}
    evaluation_labels = sorted(
        field
        for field in all_fields
        if field not in partition_metadata and is_forbidden_label_outcome_field(field)
    )
    return {
        "schema_version": schema_version("pooled_training_evaluation_corpus"),
        "hash_algorithm": "sha256_sorted_canonical_row_hashes",
        "holdout_year": holdout_year,
        "selection_training": _partition(selection),
        "evaluation": _partition(evaluation),
        "final_refit": _partition(records),
        "model_input_fields": sorted({str(field) for field in model_input_fields}),
        "evaluation_only_label_fields": evaluation_labels,
        "source_field_count": len(all_fields),
    }
