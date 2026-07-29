"""Replay an inactive immutable release beside recorded production output."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from weather.collection.live_variant_predictions import (
    band_key,
    trace_pooled_band_binary_probabilities,
)
from weather.io import sha256_file, write_json_atomic, write_text_atomic
from weather.market.market_config import event_slug_for_date
from weather.model.toronto_model import TorontoHighTempModel
from weather.paths import REPO_ROOT, data_path
from weather.release_artifacts import canonical_payload_sha256
from weather.release_serving import (
    DEFAULT_ACTIVE_RELEASE_POINTER,
    STATUS_INACTIVE_SHADOW_BOUND,
    ReleaseServingBindingError,
    VerifiedServingBundle,
    load_verified_inactive_serving_bundle,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("inactive_release_forward_shadow")
CAPTURED_INPUT_HASH_ALGORITHM = "sha256-canonical-json;omit=captured_input_hash"
DEFAULT_OUTPUT_ROOT = data_path("backtest", "inactive_release_forward_shadow")
DEFAULT_MAX_SNAPSHOTS = 2_048
DEFAULT_FLOAT_TOLERANCE = 1e-12
MAX_JSONL_LINE_BYTES = 8 * 1024 * 1024

COMPONENT_STAGE_ORDER = (
    "climatology_prior",
    "hgb_feature_model",
    "feature_blend",
    "current_observed_floor",
    "settlement_lag_adjusted",
    "wu_floor_residual",
    "late_day_lockin",
    "post_live_signals",
    "pre_calibration_model",
    "overconfidence_calibration",
    "final_model",
)
CANDIDATE_STAGE_ORDER = (
    "candidate_raw",
    "candidate_postprocessed",
    "candidate_preblend",
    "candidate_current_blend",
    "candidate_final",
)


class InactiveReleaseForwardShadowError(RuntimeError):
    """The declared forward-shadow comparison cannot be proven."""


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise InactiveReleaseForwardShadowError(
            f"{field} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise InactiveReleaseForwardShadowError(
            f"{field} must include a timezone"
        )
    return parsed


def _read_jsonl(path: Path, *, label: str, max_rows: int) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise InactiveReleaseForwardShadowError(
            f"{label} must be a regular file: {path}"
        )
    rows: list[dict[str, Any]] = []
    with path.open("rb") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if len(raw) > MAX_JSONL_LINE_BYTES:
                raise InactiveReleaseForwardShadowError(
                    f"{label} line {line_number} exceeds {MAX_JSONL_LINE_BYTES} bytes"
                )
            if not raw.strip():
                continue
            try:
                row = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise InactiveReleaseForwardShadowError(
                    f"{label} line {line_number} is invalid JSON: {exc}"
                ) from exc
            if not isinstance(row, dict):
                raise InactiveReleaseForwardShadowError(
                    f"{label} line {line_number} is not a JSON object"
                )
            rows.append(row)
            if len(rows) > max_rows:
                raise InactiveReleaseForwardShadowError(
                    f"{label} exceeds the declared {max_rows}-row bound"
                )
    return rows


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value


def _numeric_map(value: Any) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, raw in (value or {}).items():
        try:
            number = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            result[str(key)] = number
    return result


def _max_abs_delta(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    keys = set(left) | set(right)
    if not keys:
        return math.inf
    return max(abs(left.get(key, 0.0) - right.get(key, 0.0)) for key in keys)


def _matches(
    left: Mapping[str, float],
    right: Mapping[str, float],
    *,
    tolerance: float,
) -> tuple[bool, bool, float]:
    same_keys = set(left) == set(right)
    strict = same_keys and dict(left) == dict(right)
    delta = _max_abs_delta(left, right)
    return strict, same_keys and delta <= tolerance, delta


def _number(value: Any) -> float | int | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return int(round(numeric)) if abs(numeric - round(numeric)) < 1e-9 else numeric


def _band_rows(
    model_client: Any,
    distribution: Mapping[Any, Any],
    calibration_context: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in snapshot.get("bands") or []:
        if not isinstance(raw, Mapping):
            raise InactiveReleaseForwardShadowError(
                f"snapshot {snapshot.get('snapshot_id')} has a non-object band"
            )
        band = dict(raw)
        value = _number(
            band.get("bin_value_c")
            if band.get("bin_value_c") not in (None, "")
            else band.get("bin_value")
        )
        value_hi = _number(
            band.get("bin_value_hi_c")
            if band.get("bin_value_hi_c") not in (None, "")
            else band.get("bin_value_hi")
        )
        if value_hi is None:
            value_hi = value
        kind = str(band.get("bin_kind") or "")
        if kind not in {"lte", "eq", "gte"} or value is None:
            raise InactiveReleaseForwardShadowError(
                f"snapshot {snapshot.get('snapshot_id')} has an invalid band identity"
            )
        probability = model_client.bin_probability(
            distribution,
            {
                "kind": kind,
                "value": value,
                "value_hi": value_hi,
                "label": band.get("range_label"),
                "market_yes": band.get("market_yes"),
                "market_no": band.get("market_no"),
            },
            calibration_context=calibration_context,
        )
        band["bin_kind"] = kind
        band["bin_value_c"] = value
        band["bin_value_hi_c"] = value_hi
        band["model_probability"] = probability
        rows.append(band)
    if not rows:
        raise InactiveReleaseForwardShadowError(
            f"snapshot {snapshot.get('snapshot_id')} has no band context"
        )
    return rows


def _recorded_band_probabilities(
    snapshot: Mapping[str, Any],
) -> dict[str, float]:
    probabilities: dict[str, float] = {}
    for raw in snapshot.get("bands") or []:
        if not isinstance(raw, Mapping):
            continue
        key = band_key(dict(raw))
        try:
            value = float(raw.get("model_probability"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            probabilities[key] = value
    if not probabilities:
        raise InactiveReleaseForwardShadowError(
            f"snapshot {snapshot.get('snapshot_id')} has no recorded production probabilities"
        )
    return probabilities


def _first_component_divergence(
    recorded_payload: Mapping[str, Any],
    inactive_payload: Mapping[str, Any],
) -> str | None:
    recorded = recorded_payload.get("components") or {}
    inactive = inactive_payload.get("components") or {}
    if not isinstance(recorded, Mapping) or not isinstance(inactive, Mapping):
        return "distribution_components"
    ordered = [
        *COMPONENT_STAGE_ORDER,
        *sorted((set(recorded) | set(inactive)) - set(COMPONENT_STAGE_ORDER)),
    ]
    for stage in ordered:
        if canonical_payload_sha256({"value": _plain(recorded.get(stage))}) != (
            canonical_payload_sha256({"value": _plain(inactive.get(stage))})
        ):
            return f"distribution_component.{stage}"
    recorded_outer = {
        key: value for key, value in recorded_payload.items() if key != "components"
    }
    inactive_outer = {
        key: value for key, value in inactive_payload.items() if key != "components"
    }
    if canonical_payload_sha256(_plain(recorded_outer)) != canonical_payload_sha256(
        _plain(inactive_outer)
    ):
        return "distribution_components.metadata"
    return None


def _first_mapping_field_divergence(
    recorded: Mapping[str, Any],
    inactive: Mapping[str, Any],
) -> dict[str, Any] | None:
    for field in sorted(set(recorded) | set(inactive)):
        recorded_present = field in recorded
        inactive_present = field in inactive
        recorded_value = _plain(recorded.get(field))
        inactive_value = _plain(inactive.get(field))
        recorded_sha256 = canonical_payload_sha256({"value": recorded_value})
        inactive_sha256 = canonical_payload_sha256({"value": inactive_value})
        if (
            recorded_present != inactive_present
            or recorded_sha256 != inactive_sha256
        ):
            detail = {
                "field": field,
                "recorded_present": recorded_present,
                "inactive_present": inactive_present,
                "recorded_value_sha256": recorded_sha256,
                "inactive_value_sha256": inactive_sha256,
            }
            if isinstance(recorded_value, (str, int, float, bool)) or (
                recorded_value is None
            ):
                detail["recorded_value"] = recorded_value
            if isinstance(inactive_value, (str, int, float, bool)) or (
                inactive_value is None
            ):
                detail["inactive_value"] = inactive_value
            return detail
    return None


def _snapshot_first_divergence(
    *,
    feature_exact: bool,
    component_divergence: str | None,
    distribution_tolerance_match: bool,
    incumbent_tolerance_match: bool,
    candidate_stage_matches: Mapping[str, Mapping[str, Any]],
) -> str | None:
    if not feature_exact:
        return "feature_vector"
    if component_divergence:
        return component_divergence
    if not distribution_tolerance_match:
        return "base_distribution"
    if not incumbent_tolerance_match:
        return "incumbent_band_projection"
    for stage in CANDIDATE_STAGE_ORDER:
        if not candidate_stage_matches[stage]["tolerance_match"]:
            return stage
    return None


def _safe_outputs(
    *,
    release_dir: Path,
    source_paths: Sequence[Path],
    output_paths: Sequence[Path],
) -> None:
    resolved_sources = {path.resolve() for path in source_paths}
    resolved_outputs = [path.resolve(strict=False) for path in output_paths]
    if len(set(resolved_outputs)) != len(resolved_outputs):
        raise InactiveReleaseForwardShadowError(
            "forward-shadow outputs must be distinct"
        )
    for path in resolved_outputs:
        if path in resolved_sources or path.is_relative_to(release_dir):
            raise InactiveReleaseForwardShadowError(
                "forward-shadow output aliases a source or immutable release path"
            )


def generate_inactive_release_forward_shadow(
    *,
    release_dir: str | Path,
    expected_manifest_sha256: str,
    market_id: str,
    target_date: str | date,
    captured_inputs_path: str | Path,
    snapshot_tape_path: str | Path,
    window_start: str | datetime,
    window_end: str | datetime,
    active_pointer_path: str | Path = DEFAULT_ACTIVE_RELEASE_POINTER,
    repo_root: str | Path = REPO_ROOT,
    check_runtime: bool = True,
    max_snapshots: int = DEFAULT_MAX_SNAPSHOTS,
    float_tolerance: float = DEFAULT_FLOAT_TOLERANCE,
    now: datetime | None = None,
    bundle_loader: Callable[..., VerifiedServingBundle] = (
        load_verified_inactive_serving_bundle
    ),
    model_factory: Callable[..., Any] = TorontoHighTempModel,
    trace_runner: Callable[..., Mapping[str, Any]] = (
        trace_pooled_band_binary_probabilities
    ),
) -> dict[str, Any]:
    """Build an exact per-instant inactive-release/production comparison."""

    release_root = Path(release_dir).resolve()
    captured_path = Path(captured_inputs_path).resolve()
    snapshots_path = Path(snapshot_tape_path).resolve()
    start = (
        window_start.astimezone(timezone.utc)
        if isinstance(window_start, datetime) and window_start.tzinfo is not None
        else _parse_timestamp(window_start, field="window_start").astimezone(
            timezone.utc
        )
    )
    end = (
        window_end.astimezone(timezone.utc)
        if isinstance(window_end, datetime) and window_end.tzinfo is not None
        else _parse_timestamp(window_end, field="window_end").astimezone(
            timezone.utc
        )
    )
    if end <= start:
        raise InactiveReleaseForwardShadowError(
            "window_end must be later than window_start"
        )
    if not 1 <= int(max_snapshots) <= DEFAULT_MAX_SNAPSHOTS:
        raise InactiveReleaseForwardShadowError(
            f"max_snapshots must be in [1, {DEFAULT_MAX_SNAPSHOTS}]"
        )
    if (
        not math.isfinite(float(float_tolerance))
        or float_tolerance < 0
        or float_tolerance > 1e-6
    ):
        raise InactiveReleaseForwardShadowError(
            "float_tolerance must be finite and in [0, 1e-6]"
        )
    market = str(market_id or "").strip()
    day = (
        target_date
        if isinstance(target_date, date)
        else date.fromisoformat(str(target_date))
    )
    expected_event_slug = event_slug_for_date(day, market)
    pointer_path = Path(active_pointer_path).resolve()
    pointer_present_before = pointer_path.exists()
    pointer_sha256_before = (
        sha256_file(pointer_path) if pointer_present_before else None
    )
    source_hashes = {
        str(captured_path): sha256_file(captured_path),
        str(snapshots_path): sha256_file(snapshots_path),
    }
    try:
        bundle = bundle_loader(
            release_root,
            expected_manifest_sha256=expected_manifest_sha256,
            active_pointer_path=pointer_path,
            repo_root=repo_root,
            check_runtime=check_runtime,
        )
    except (ReleaseServingBindingError, OSError) as exc:
        raise InactiveReleaseForwardShadowError(
            f"inactive release verification failed: {type(exc).__name__}: {exc}"
        ) from exc
    if (
        bundle.status != STATUS_INACTIVE_SHADOW_BOUND
        or bundle.pointer_present
        or not bundle.base_model_bound
    ):
        raise InactiveReleaseForwardShadowError(
            "inactive release did not bind as a complete non-pointer shadow graph"
        )
    route = (bundle.route.get("markets") or {}).get(market)
    if (
        not isinstance(route, Mapping)
        or route.get("decision") not in {"promote", "shadow"}
        or not str(route.get("candidate_variant_id") or "")
    ):
        raise InactiveReleaseForwardShadowError(
            f"inactive release has no executable shadow/promote route for {market!r}"
        )
    if str(bundle.model_bundle.get("prediction_mode") or "band_binary") != (
        "band_binary"
    ):
        raise InactiveReleaseForwardShadowError(
            "forward-shadow stage trace currently requires a band_binary release"
        )

    captured_rows = _read_jsonl(
        captured_path,
        label="captured input tape",
        max_rows=int(max_snapshots) * 4,
    )
    selected: list[dict[str, Any]] = []
    for row in captured_rows:
        captured = _parse_timestamp(
            row.get("captured_at_utc"),
            field="captured_at_utc",
        ).astimezone(timezone.utc)
        if start <= captured < end:
            if (
                str(row.get("target_date") or "") != day.isoformat()
                or str(row.get("event_slug") or "") != expected_event_slug
            ):
                raise InactiveReleaseForwardShadowError(
                    "declared window contains a captured input for another "
                    "market/day"
                )
            expected_hash = canonical_payload_sha256(
                row,
                omit=("captured_input_hash",),
            )
            if (
                row.get("captured_input_hash_algorithm")
                != CAPTURED_INPUT_HASH_ALGORITHM
                or row.get("captured_input_hash") != expected_hash
            ):
                claimed_hash = str(row.get("captured_input_hash") or "")
                unhashed = {
                    key: value
                    for key, value in row.items()
                    if key != "captured_input_hash"
                }
                insertion_order_hash = hashlib.sha256(
                    json.dumps(
                        unhashed,
                        sort_keys=False,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    ).encode("utf-8")
                ).hexdigest()
                noncanonical_match = (
                    claimed_hash == insertion_order_hash
                    and claimed_hash != expected_hash
                )
                raise InactiveReleaseForwardShadowError(
                    f"captured input {row.get('snapshot_id')} has an invalid "
                    f"self-hash: claimed={claimed_hash or '<absent>'}, "
                    f"canonical={expected_hash}, "
                    "claimed_matches_noncanonical_insertion_order="
                    f"{str(noncanonical_match).lower()}"
                )
            selected.append(row)
    if not selected:
        raise InactiveReleaseForwardShadowError(
            "declared window contains no captured inputs"
        )
    if len(selected) > int(max_snapshots):
        raise InactiveReleaseForwardShadowError(
            "declared window exceeds max_snapshots"
        )
    by_snapshot = {
        str(row.get("snapshot_id") or ""): row
        for row in selected
        if str(row.get("snapshot_id") or "")
    }
    if len(by_snapshot) != len(selected):
        raise InactiveReleaseForwardShadowError(
            "captured input window has missing or duplicate snapshot IDs"
        )
    snapshot_rows = _read_jsonl(
        snapshots_path,
        label="snapshot tape",
        max_rows=DEFAULT_MAX_SNAPSHOTS * 4,
    )
    snapshots: dict[str, dict[str, Any]] = {}
    for row in snapshot_rows:
        snapshot_id = str(row.get("snapshot_id") or "")
        if snapshot_id not in by_snapshot:
            continue
        if snapshot_id in snapshots:
            raise InactiveReleaseForwardShadowError(
                f"snapshot tape repeats {snapshot_id}"
            )
        snapshots[snapshot_id] = row
    missing = sorted(set(by_snapshot) - set(snapshots))
    if missing:
        raise InactiveReleaseForwardShadowError(
            f"captured inputs lack sibling snapshots: {missing[:10]}"
        )

    try:
        model_client = model_factory(
            target_date=day,
            market_id=market,
            serving_bundle=bundle,
        )
    except Exception as exc:
        raise InactiveReleaseForwardShadowError(
            f"inactive release model construction failed: {type(exc).__name__}: {exc}"
        ) from exc

    instant_rows: list[dict[str, Any]] = []
    strict_partition_matches = {
        "inactive_incumbent": 0,
        **{stage: 0 for stage in CANDIDATE_STAGE_ORDER},
    }
    tolerance_partition_matches = dict(strict_partition_matches)
    first_divergence: dict[str, Any] | None = None
    for snapshot_id in sorted(
        by_snapshot,
        key=lambda value: str(by_snapshot[value].get("captured_at_utc") or ""),
    ):
        record = by_snapshot[snapshot_id]
        snapshot = snapshots[snapshot_id]
        identity_mismatches = [
            field
            for field in (
                "captured_at_utc",
                "event_slug",
                "model_version",
            )
            if str(snapshot.get(field) or "") != str(record.get(field) or "")
        ]
        if identity_mismatches:
            raise InactiveReleaseForwardShadowError(
                f"snapshot {snapshot_id} does not match its captured input: "
                f"{identity_mismatches}"
            )
        if _numeric_map(snapshot.get("distribution")) != _numeric_map(
            record.get("recorded_distribution")
        ):
            raise InactiveReleaseForwardShadowError(
                f"snapshot {snapshot_id} distribution does not match its "
                "captured-input fidelity canary"
            )
        built_at = _parse_timestamp(
            record.get("built_at") or record.get("captured_at_local"),
            field="built_at",
        )
        sources = dict(record.get("sources") or {})
        result = model_client.estimate_distribution_result(sources, now=built_at)
        inactive_distribution = _numeric_map(
            dict(getattr(result, "distribution", {}) or {})
        )
        recorded_distribution = _numeric_map(
            record.get("recorded_distribution") or snapshot.get("distribution")
        )
        distribution_strict, distribution_close, distribution_delta = _matches(
            recorded_distribution,
            inactive_distribution,
            tolerance=float(float_tolerance),
        )
        history = model_client.source_data(sources, "wu_history") or {}
        cutoff_hour = model_client.effective_intraday_cutoff_hour(
            built_at,
            history.get("rows") or [],
        )
        model_version = model_client.get_model_version_string()
        inactive_feature = dict(
            model_client.live_feature_record(
                sources,
                cutoff_hour,
                captured_at=built_at,
                model_version=model_version,
            )
            or {}
        )
        recorded_feature = dict(snapshot.get("feature_vector") or {})
        feature_hash_recorded = canonical_payload_sha256(recorded_feature)
        feature_hash_inactive = canonical_payload_sha256(inactive_feature)
        feature_exact = feature_hash_recorded == feature_hash_inactive
        feature_divergence = _first_mapping_field_divergence(
            recorded_feature,
            inactive_feature,
        )
        inactive_components = dict(
            getattr(result, "component_payload", {}) or {}
        )
        recorded_components = dict(
            snapshot.get("distribution_components") or {}
        )
        component_divergence = _first_component_divergence(
            recorded_components,
            inactive_components,
        )
        inactive_bands = _band_rows(
            model_client,
            getattr(result, "distribution", {}) or {},
            dict(getattr(result, "calibration_context", {}) or {}),
            snapshot,
        )
        inactive_incumbent = {
            band_key(row): float(row["model_probability"])
            for row in inactive_bands
        }
        recorded_production = _recorded_band_probabilities(snapshot)
        incumbent_strict, incumbent_close, incumbent_delta = _matches(
            recorded_production,
            inactive_incumbent,
            tolerance=float(float_tolerance),
        )
        trace = trace_runner(
            _plain(bundle.model_bundle),
            inactive_feature,
            inactive_bands,
            {
                "market_id": market,
                "captured_at": built_at,
                "model": {
                    "feature_vector": inactive_feature,
                    "source_diagnostics": model_client.source_diagnostics(
                        sources
                    ),
                },
            },
        )
        stages = {
            stage: _numeric_map((trace.get("stages") or {}).get(stage))
            for stage in CANDIDATE_STAGE_ORDER
        }
        if any(not stages[stage] for stage in CANDIDATE_STAGE_ORDER):
            raise InactiveReleaseForwardShadowError(
                f"inactive release produced an incomplete trace for {snapshot_id}"
            )
        stage_matches: dict[str, dict[str, Any]] = {}
        for stage in CANDIDATE_STAGE_ORDER:
            strict, close, delta = _matches(
                recorded_production,
                stages[stage],
                tolerance=float(float_tolerance),
            )
            stage_matches[stage] = {
                "strict_match": strict,
                "tolerance_match": close,
                "max_abs_delta": delta,
            }
            strict_partition_matches[stage] += int(strict)
            tolerance_partition_matches[stage] += int(close)
        strict_partition_matches["inactive_incumbent"] += int(incumbent_strict)
        tolerance_partition_matches["inactive_incumbent"] += int(
            incumbent_close
        )
        divergence = _snapshot_first_divergence(
            feature_exact=feature_exact,
            component_divergence=component_divergence,
            distribution_tolerance_match=distribution_close,
            incumbent_tolerance_match=incumbent_close,
            candidate_stage_matches=stage_matches,
        )
        if divergence and first_divergence is None:
            first_divergence = {
                "snapshot_id": snapshot_id,
                "captured_at_utc": record["captured_at_utc"],
                "stage": divergence,
            }
        probability_rows = []
        probability_keys = set(recorded_production) | set(inactive_incumbent)
        for stage in CANDIDATE_STAGE_ORDER:
            probability_keys.update(stages[stage])
        for key in sorted(probability_keys):
            probability_rows.append(
                {
                    "band_key": key,
                    "recorded_production_probability": recorded_production[key],
                    "inactive_incumbent_probability": inactive_incumbent.get(key),
                    **{
                        f"{stage}_probability": stages[stage].get(key)
                        for stage in CANDIDATE_STAGE_ORDER
                    },
                }
            )
        instant_rows.append(
            {
                "snapshot_id": snapshot_id,
                "captured_at_utc": record["captured_at_utc"],
                "captured_input_hash": record["captured_input_hash"],
                "captured_input_identity": {
                    "event_slug": record.get("event_slug"),
                    "target_date": record.get("target_date"),
                    "model_version": record.get("model_version"),
                    "model_identity": record.get("model_identity"),
                    "release_id": record.get("release_id"),
                    "release_manifest_sha256": record.get(
                        "release_manifest_sha256"
                    ),
                    "release_pointer_sha256": record.get(
                        "release_pointer_sha256"
                    ),
                    "release_identity_status": record.get(
                        "release_identity_status"
                    ),
                    "runtime_identity": record.get("runtime_identity"),
                },
                "inactive_release_identity": {
                    "release_id": bundle.release_id,
                    "manifest_sha256": bundle.manifest_sha256,
                    "candidate_id": route["candidate_variant_id"],
                    "candidate_artifact_sha256": bundle.artifact_hashes.get(
                        "pooled_band_model"
                    ),
                    "postprocess_sha256": bundle.artifact_hashes.get(
                        "pooled_postprocessor_metadata"
                    ),
                },
                "feature_vector": {
                    "recorded_sha256": feature_hash_recorded,
                    "inactive_sha256": feature_hash_inactive,
                    "exact_match": feature_exact,
                    "first_field_divergence": feature_divergence,
                },
                "distribution_components": {
                    "recorded_sha256": canonical_payload_sha256(
                        recorded_components
                    ),
                    "inactive_sha256": canonical_payload_sha256(
                        inactive_components
                    ),
                    "first_divergence": component_divergence,
                },
                "base_distribution": {
                    "strict_match": distribution_strict,
                    "tolerance_match": distribution_close,
                    "max_abs_delta": distribution_delta,
                },
                "inactive_incumbent": {
                    "strict_match": incumbent_strict,
                    "tolerance_match": incumbent_close,
                    "max_abs_delta": incumbent_delta,
                },
                "candidate_stage_matches_recorded_production": stage_matches,
                "first_pipeline_divergence": divergence,
                "probabilities": probability_rows,
            }
        )

    changed = [
        path
        for path, expected in source_hashes.items()
        if sha256_file(path) != expected
    ]
    if changed:
        raise InactiveReleaseForwardShadowError(
            f"source tapes changed during the comparison: {changed}"
        )
    pointer_present_after = pointer_path.exists()
    pointer_sha256_after = (
        sha256_file(pointer_path) if pointer_present_after else None
    )
    if (
        pointer_present_after != pointer_present_before
        or pointer_sha256_after != pointer_sha256_before
    ):
        raise InactiveReleaseForwardShadowError(
            "active release pointer changed during the comparison"
        )
    generated = now or datetime.now(timezone.utc)
    if generated.tzinfo is None:
        raise InactiveReleaseForwardShadowError("now must include a timezone")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "evidence_contract": "inactive_release_forward_shadow",
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "PASS",
        "comparison_status": (
            "MATCH"
            if strict_partition_matches["candidate_final"] == len(instant_rows)
            else "DIVERGED"
        ),
        "release_id": bundle.release_id,
        "release_manifest_sha256": bundle.manifest_sha256,
        "inactive_bundle_status": bundle.status,
        "active_pointer_authority_used": False,
        "active_pointer_observation": {
            "path": str(pointer_path),
            "present_before": pointer_present_before,
            "present_after": pointer_present_after,
            "sha256_before": pointer_sha256_before,
            "sha256_after": pointer_sha256_after,
            "unchanged": True,
            "target_release_was_inactive": True,
        },
        "market_id": market,
        "target_date": day.isoformat(),
        "window": {
            "start_utc": start.isoformat(),
            "end_utc": end.isoformat(),
            "end_exclusive": True,
        },
        "source_tapes": [
            {"path": path, "sha256": digest}
            for path, digest in sorted(source_hashes.items())
        ],
        "comparison_contract": {
            "recorded_production_field": "snapshots.jsonl.bands[].model_probability",
            "captured_input_identity": "replay_inputs.jsonl.captured_input_hash",
            "float_tolerance": float(float_tolerance),
            "strict_whole_partition_match": (
                "same band-key set and exact decoded float equality for every band"
            ),
            "candidate_stage_order": list(CANDIDATE_STAGE_ORDER),
        },
        "summary": {
            "snapshot_count": len(instant_rows),
            "band_row_count": sum(
                len(row["probabilities"]) for row in instant_rows
            ),
            "strict_whole_partition_matches": strict_partition_matches,
            "tolerance_whole_partition_matches": tolerance_partition_matches,
            "first_pipeline_divergence": first_divergence,
        },
        "instants": instant_rows,
    }
    payload["evidence_sha256"] = canonical_payload_sha256(
        payload,
        omit=("evidence_sha256",),
    )
    return payload


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Inactive release forward-shadow parity",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Comparison: `{payload.get('comparison_status')}`",
        f"- Release: `{payload.get('release_id')}`",
        f"- Manifest: `{payload.get('release_manifest_sha256')}`",
        f"- Market/day: `{payload.get('market_id')}` / `{payload.get('target_date')}`",
        (
            f"- Window: `{(payload.get('window') or {}).get('start_utc')}` to "
            f"`{(payload.get('window') or {}).get('end_utc')}` (end exclusive)"
        ),
        f"- Snapshots: `{summary.get('snapshot_count')}`",
        f"- Band rows: `{summary.get('band_row_count')}`",
        "",
        "## Whole-partition agreement",
        "",
        "| Stage | Strict | Within tolerance |",
        "| :--- | ---: | ---: |",
    ]
    strict = summary.get("strict_whole_partition_matches") or {}
    close = summary.get("tolerance_whole_partition_matches") or {}
    for stage in ("inactive_incumbent", *CANDIDATE_STAGE_ORDER):
        lines.append(f"| `{stage}` | {strict.get(stage, 0)} | {close.get(stage, 0)} |")
    first = summary.get("first_pipeline_divergence")
    lines.extend(
        [
            "",
            "## First pipeline divergence",
            "",
            (
                "None; every inactive candidate-final partition exactly matched "
                "recorded production."
                if not first
                else (
                    f"`{first.get('stage')}` at `{first.get('snapshot_id')}` "
                    f"(`{first.get('captured_at_utc')}`)."
                )
            ),
            "",
            "This report is shadow evidence only. It does not activate the release, "
            "change serving, or authorize promotion or trading.",
            "",
        ]
    )
    return "\n".join(lines)


def default_output_paths(
    market_id: str,
    target_date: str,
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
) -> tuple[Path, Path]:
    safe_market = str(market_id or "").strip()
    safe_date = str(target_date or "").strip()
    if (
        not safe_market
        or not safe_date
        or any(value in {".", ".."} for value in (safe_market, safe_date))
        or any("/" in value or "\\" in value for value in (safe_market, safe_date))
    ):
        raise InactiveReleaseForwardShadowError(
            "market/date are unsafe for output paths"
        )
    root = Path(output_root) / safe_market / safe_date
    return root / "forward_shadow.json", root / "forward_shadow.md"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay an exact inactive immutable release beside recorded production "
            "over one declared captured-input window."
        )
    )
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--market-id", required=True)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--captured-inputs", type=Path, required=True)
    parser.add_argument("--snapshot-tape", type=Path, required=True)
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--window-end", required=True)
    parser.add_argument(
        "--active-release-pointer",
        type=Path,
        default=DEFAULT_ACTIVE_RELEASE_POINTER,
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--max-snapshots", type=int, default=DEFAULT_MAX_SNAPSHOTS)
    parser.add_argument(
        "--float-tolerance",
        type=float,
        default=DEFAULT_FLOAT_TOLERANCE,
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--report-out", type=Path, default=None)
    parser.add_argument("--integrity-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    default_json, default_report = default_output_paths(
        args.market_id,
        args.target_date,
        output_root=args.output_root,
    )
    json_out = args.json_out or default_json
    report_out = args.report_out or default_report
    try:
        _safe_outputs(
            release_dir=args.release_dir.resolve(),
            source_paths=(args.captured_inputs, args.snapshot_tape),
            output_paths=(json_out, report_out),
        )
        payload = generate_inactive_release_forward_shadow(
            release_dir=args.release_dir,
            expected_manifest_sha256=args.manifest_sha256,
            market_id=args.market_id,
            target_date=args.target_date,
            captured_inputs_path=args.captured_inputs,
            snapshot_tape_path=args.snapshot_tape,
            window_start=args.window_start,
            window_end=args.window_end,
            active_pointer_path=args.active_release_pointer,
            repo_root=args.repo_root,
            check_runtime=not args.integrity_only,
            max_snapshots=args.max_snapshots,
            float_tolerance=args.float_tolerance,
        )
        write_json_atomic(json_out, payload, trailing_newline=True)
        write_text_atomic(report_out, render_markdown(payload))
    except Exception as exc:  # noqa: BLE001 - operational CLI must fail closed
        print(
            json.dumps(
                {
                    "status": "BLOCK",
                    "error": f"{type(exc).__name__}: {exc}",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": payload["status"],
                "comparison_status": payload["comparison_status"],
                "release_id": payload["release_id"],
                "snapshot_count": payload["summary"]["snapshot_count"],
                "first_pipeline_divergence": payload["summary"][
                    "first_pipeline_divergence"
                ],
                "json_out": str(json_out),
                "report_out": str(report_out),
                "evidence_sha256": payload["evidence_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
