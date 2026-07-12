"""Pure runtime for the quarantined ``ResidualDistributionV1`` candidate.

The candidate deliberately does not share the incumbent distribution's
postprocessing stack.  It predicts a canonical-Fahrenheit residual around a
point-in-time forecast anchor, builds one Gaussian density, applies only the
printed observed-high settlement constraint, projects that density into the
market's native bands, and finally applies one simplex temperature.

The module is intentionally side-effect free so live capture and replay can
call the same function.  It never substitutes another model on failure.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline

from weather.market.market_registry import REGISTRY
from weather.model.continuous_density import (
    band_probability_from_density,
    bucket_interval_native,
    canonical_grid_f,
    native_interval_to_f,
    native_to_f,
    normalize_density,
)
from weather.units import round_half_up


ARTIFACT_SCHEMA_VERSION = "residual_distribution_v1_v0.1"
PREDICTION_MODE = "residual_distribution_v1"

FEATURE_KINDS = frozenset(
    {"absolute_temperature", "temperature_delta", "numeric", "categorical"}
)
SOURCE_STATES = frozenset({"fresh", "stale", "failed", "unknown"})
SOURCE_STATE_RANK = {"fresh": 0, "stale": 1, "unknown": 2, "failed": 3}
MAX_GRID_POINTS = 10_000

DEFAULT_FEATURE_SPECS = {
    "forecast_high": "absolute_temperature",
    "high_so_far": "absolute_temperature",
    "current_temp": "absolute_temperature",
    "rise_from_7am": "temperature_delta",
    "warming_rate_2h": "temperature_delta",
    "hours_at_peak": "numeric",
    "forecast_gap": "temperature_delta",
    "forecast_source_count": "numeric",
    "forecast_disagreement": "temperature_delta",
    "minutes_since_cutoff": "numeric",
    "live_reading_temp": "absolute_temperature",
    "live_reading_minus_high": "temperature_delta",
    "guidance_impossible_source_count": "numeric",
    "startup_feature_quarantined_flag": "numeric",
    "cutoff_hour": "numeric",
}
DEFAULT_REQUIRED_FEATURES = ("forecast_high",)
SOURCE_HEALTH_AGGREGATE_FEATURES = (
    "source_health_fresh_count",
    "source_health_stale_count",
    "source_health_failed_count",
    "source_health_unknown_count",
    "source_health_source_count",
    "source_health_all_fresh",
    "source_health_any_degraded",
)


class ResidualArtifactError(ValueError):
    """The serialized candidate does not satisfy its runtime contract."""


class CandidateAbstention(ValueError):
    """A valid artifact cannot safely score the supplied point-in-time input."""

    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def default_feature_contract(
    feature_schema_version: str,
    *,
    required_sources: Sequence[str] = ("open_meteo",),
    allowed_source_states: Sequence[str] = tuple(sorted(SOURCE_STATES)),
) -> dict[str, Any]:
    """Return the artifact-like feature template used before a model is fitted.

    Corpus materialization and training can call
    :func:`canonical_candidate_features` with this template.  The fitted
    artifact adds the Ridge pipeline and density/calibration fields without
    changing the row definition.
    """

    schema = str(feature_schema_version or "").strip()
    if not schema:
        raise ValueError("feature_schema_version is required")
    sources = [str(source or "").strip() for source in required_sources]
    if any(not source for source in sources) or len(set(sources)) != len(sources):
        raise ValueError("required_sources must be unique non-empty names")
    states = [str(state or "").strip() for state in allowed_source_states]
    if not states or not set(states) <= SOURCE_STATES:
        raise ValueError("allowed_source_states must contain supported source states")

    feature_names = ["market_id"]
    for name in DEFAULT_FEATURE_SPECS:
        feature_names.extend((name, f"{name}_available", f"{name}_missing"))
    feature_names.extend(SOURCE_HEALTH_AGGREGATE_FEATURES)
    for source in sources:
        prefix = f"source_{_source_slug(source)}"
        feature_names.extend(
            (
                f"{prefix}_present",
                f"{prefix}_available",
                f"{prefix}_fresh",
                f"{prefix}_stale",
                f"{prefix}_failed",
                f"{prefix}_unknown",
                f"{prefix}_age_ratio",
                f"{prefix}_age_ratio_available",
            )
        )
    return {
        "feature_schema_version": schema,
        "feature_names": feature_names,
        "feature_contract": {
            "features": dict(DEFAULT_FEATURE_SPECS),
            "required": list(DEFAULT_REQUIRED_FEATURES),
        },
        "source_health_policy": {
            "required_sources": sources,
            "allowed_states": sorted(set(states)),
        },
    }


def _finite_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ResidualArtifactError(f"artifact field {field!r} is required")
    return text


def _unique_strings(values: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(values, (list, tuple)):
        raise ResidualArtifactError(f"artifact field {field!r} must be a list")
    output = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            raise ResidualArtifactError(f"artifact field {field!r} contains an empty value")
        output.append(text)
    if len(set(output)) != len(output):
        raise ResidualArtifactError(f"artifact field {field!r} contains duplicates")
    if not output and not allow_empty:
        raise ResidualArtifactError(f"artifact field {field!r} cannot be empty")
    return output


def _ridge_pipeline(value: Any) -> Pipeline:
    if not isinstance(value, Pipeline) or not value.steps:
        raise ResidualArtifactError("artifact pipeline must be a fitted sklearn Pipeline")
    if not isinstance(value.steps[-1][1], Ridge):
        raise ResidualArtifactError("artifact pipeline must end with sklearn.linear_model.Ridge")
    return value


def validate_artifact(artifact: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate and normalize the strict v0.1 pickle payload."""

    if not isinstance(artifact, Mapping):
        raise ResidualArtifactError("artifact must be a mapping")
    if artifact.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise ResidualArtifactError(
            f"artifact schema must be {ARTIFACT_SCHEMA_VERSION!r}, "
            f"got {artifact.get('schema_version')!r}"
        )
    if artifact.get("prediction_mode") != PREDICTION_MODE:
        raise ResidualArtifactError(
            f"artifact prediction_mode must be {PREDICTION_MODE!r}"
        )
    if str(artifact.get("canonical_unit") or "").upper() != "F":
        raise ResidualArtifactError("artifact canonical_unit must be 'F'")

    feature_schema_version = _required_text(
        artifact.get("feature_schema_version"), "feature_schema_version"
    )
    feature_names = _unique_strings(artifact.get("feature_names"), "feature_names")
    pipeline = _ridge_pipeline(artifact.get("pipeline"))

    contract = artifact.get("feature_contract")
    if not isinstance(contract, Mapping):
        raise ResidualArtifactError("artifact feature_contract must be a mapping")
    feature_specs = contract.get("features")
    if not isinstance(feature_specs, Mapping) or not feature_specs:
        raise ResidualArtifactError("artifact feature_contract.features must be non-empty")
    normalized_specs: dict[str, str] = {}
    for raw_name, raw_kind in feature_specs.items():
        name = str(raw_name or "").strip()
        kind = str(raw_kind or "").strip()
        if not name or kind not in FEATURE_KINDS:
            raise ResidualArtifactError(
                "artifact feature kinds must be one of " + ", ".join(sorted(FEATURE_KINDS))
            )
        normalized_specs[name] = kind
    if normalized_specs.get("forecast_high") != "absolute_temperature":
        raise ResidualArtifactError(
            "feature_contract must declare forecast_high as absolute_temperature"
        )
    required_features = _unique_strings(
        contract.get("required") or [], "feature_contract.required", allow_empty=True
    )
    if "forecast_high" not in required_features:
        raise ResidualArtifactError("forecast_high must be a required feature")
    undeclared_required = sorted(set(required_features) - set(normalized_specs))
    if undeclared_required:
        raise ResidualArtifactError(
            "required features are undeclared: " + ", ".join(undeclared_required)
        )

    source_policy = artifact.get("source_health_policy")
    if not isinstance(source_policy, Mapping):
        raise ResidualArtifactError("artifact source_health_policy must be a mapping")
    required_sources = _unique_strings(
        source_policy.get("required_sources") or [],
        "source_health_policy.required_sources",
        allow_empty=True,
    )
    allowed_states = set(
        _unique_strings(
            source_policy.get("allowed_states"),
            "source_health_policy.allowed_states",
        )
    )
    if not allowed_states <= SOURCE_STATES:
        raise ResidualArtifactError(
            "source_health_policy.allowed_states contains an unsupported state"
        )
    source_slugs = [_source_slug(source) for source in required_sources]
    if len(set(source_slugs)) != len(source_slugs):
        raise ResidualArtifactError("required source names collide after normalization")

    sigma_f = _finite_float(artifact.get("residual_sigma_f"))
    if sigma_f is None or sigma_f <= 0:
        raise ResidualArtifactError("artifact residual_sigma_f must be positive")
    low_f = _finite_float(artifact.get("grid_low_f"))
    high_f = _finite_float(artifact.get("grid_high_f"))
    step_f = _finite_float(artifact.get("grid_step_f"))
    if low_f is None or high_f is None or step_f is None or low_f >= high_f or step_f <= 0:
        raise ResidualArtifactError("artifact canonical grid is invalid")
    point_count = int(math.floor((high_f - low_f) / step_f + 1e-9)) + 1
    if point_count < 2 or point_count > MAX_GRID_POINTS:
        raise ResidualArtifactError(
            f"artifact canonical grid must contain between 2 and {MAX_GRID_POINTS} points"
        )

    calibration = artifact.get("calibration")
    if not isinstance(calibration, Mapping):
        raise ResidualArtifactError("artifact calibration must be a mapping")
    calibration_method = str(calibration.get("method") or "").strip()
    if calibration_method not in {"simplex_temperature", "identity"}:
        raise ResidualArtifactError(
            "artifact calibration method must be simplex_temperature or identity"
        )
    temperature = _finite_float(calibration.get("temperature", 1.0))
    if temperature is None or temperature <= 0:
        raise ResidualArtifactError("artifact calibration temperature must be positive")
    if calibration_method == "identity" and not math.isclose(
        temperature, 1.0, rel_tol=0.0, abs_tol=1e-12
    ):
        raise ResidualArtifactError("identity calibration requires temperature=1")

    normalized = dict(artifact)
    normalized.update(
        {
            "feature_schema_version": feature_schema_version,
            "feature_names": feature_names,
            "pipeline": pipeline,
            "feature_contract": {
                "features": normalized_specs,
                "required": required_features,
            },
            "source_health_policy": {
                "required_sources": required_sources,
                "allowed_states": sorted(allowed_states),
            },
            "residual_sigma_f": sigma_f,
            "grid_low_f": low_f,
            "grid_high_f": high_f,
            "grid_step_f": step_f,
            "calibration": {
                **dict(calibration),
                "method": calibration_method,
                "temperature": temperature,
            },
        }
    )
    return normalized


def _source_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
    if not slug:
        raise ResidualArtifactError("source name cannot normalize to an empty slug")
    return slug


def _canonical_source_state(value: Any) -> str:
    state = str(value or "").strip().lower()
    if state in {"fresh", "ok", "healthy", "complete", "pass"}:
        return "fresh"
    if state in {"stale", "stale_cache", "degraded", "partial", "warn"}:
        return "stale"
    if state in {"failed", "failure", "error", "unavailable", "blocked", "block"}:
        return "failed"
    return "unknown"


def _source_health_features(
    source_diagnostics: Sequence[Mapping[str, Any]] | None,
    *,
    required_sources: Sequence[str],
    allowed_states: set[str],
) -> dict[str, Any]:
    by_source: dict[str, dict[str, Any]] = {}
    if source_diagnostics is not None and (
        isinstance(source_diagnostics, (str, bytes))
        or not isinstance(source_diagnostics, Sequence)
    ):
        raise CandidateAbstention(
            "source_state", "source diagnostics are not a sequence"
        )
    for raw in source_diagnostics or []:
        if not isinstance(raw, Mapping):
            continue
        source = str(raw.get("source") or "").strip()
        if not source:
            continue
        state = _canonical_source_state(raw.get("status"))
        current = by_source.get(source)
        # Duplicate diagnostics fail closed by retaining the worst state and
        # greatest observed age ratio.
        age = _finite_float(raw.get("age_minutes"))
        ttl = _finite_float(raw.get("ttl_minutes"))
        age_ratio = age / ttl if age is not None and ttl is not None and ttl > 0 else None
        if current is None:
            by_source[source] = {"state": state, "age_ratio": age_ratio}
        else:
            if SOURCE_STATE_RANK[state] > SOURCE_STATE_RANK[current["state"]]:
                current["state"] = state
            if age_ratio is not None:
                old_ratio = current.get("age_ratio")
                current["age_ratio"] = age_ratio if old_ratio is None else max(old_ratio, age_ratio)

    state_counts = {state: 0 for state in SOURCE_STATES}
    for row in by_source.values():
        state_counts[row["state"]] += 1
    if not by_source:
        state_counts["unknown"] = max(1, len(required_sources))

    output: dict[str, Any] = {
        "source_health_fresh_count": float(state_counts["fresh"]),
        "source_health_stale_count": float(state_counts["stale"]),
        "source_health_failed_count": float(state_counts["failed"]),
        "source_health_unknown_count": float(state_counts["unknown"]),
        "source_health_source_count": float(len(by_source)),
        "source_health_all_fresh": 1.0
        if by_source and all(row["state"] == "fresh" for row in by_source.values())
        else 0.0,
        "source_health_any_degraded": 1.0
        if not by_source or any(row["state"] != "fresh" for row in by_source.values())
        else 0.0,
    }
    for source in required_sources:
        source_row = by_source.get(source) or {"state": "unknown", "age_ratio": None}
        state = source_row["state"]
        if state not in allowed_states:
            raise CandidateAbstention(
                "source_state",
                f"required source {source!r} has disallowed state {state!r}",
            )
        prefix = f"source_{_source_slug(source)}"
        output[f"{prefix}_present"] = 1.0 if source in by_source else 0.0
        output[f"{prefix}_available"] = 1.0 if state in {"fresh", "stale"} else 0.0
        for candidate_state in SOURCE_STATES:
            output[f"{prefix}_{candidate_state}"] = 1.0 if state == candidate_state else 0.0
        age_ratio = source_row.get("age_ratio")
        output[f"{prefix}_age_ratio"] = math.nan if age_ratio is None else float(age_ratio)
        output[f"{prefix}_age_ratio_available"] = 0.0 if age_ratio is None else 1.0
    return output


def _native_delta_to_f(value: float, unit: str) -> float:
    return float(value) * 9.0 / 5.0 if unit == "C" else float(value)


def canonical_candidate_features(
    *,
    artifact: Mapping[str, Any],
    feature_vector: Mapping[str, Any],
    source_diagnostics: Sequence[Mapping[str, Any]] | None,
    market_id: str,
    unit: str,
) -> dict[str, Any]:
    """Create the exact flat candidate input row in canonical Fahrenheit."""

    if not isinstance(feature_vector, Mapping):
        raise CandidateAbstention("missing_forecast_anchor", "feature vector is absent")
    expected_schema = artifact["feature_schema_version"]
    actual_schema = str(feature_vector.get("feature_schema_version") or "").strip()
    if actual_schema != expected_schema:
        raise CandidateAbstention(
            "feature_schema",
            f"feature schema mismatch: expected {expected_schema!r}, got {actual_schema!r}",
        )

    output: dict[str, Any] = {"market_id": market_id, "unit": "F"}
    feature_contract = artifact["feature_contract"]
    required = set(feature_contract["required"])
    for name, kind in feature_contract["features"].items():
        raw = feature_vector.get(name)
        if kind == "categorical":
            value = str(raw).strip() if raw not in (None, "") else None
        else:
            numeric = _finite_float(raw)
            if numeric is None:
                value = None
            elif kind == "absolute_temperature":
                value = native_to_f(numeric, unit)
            elif kind == "temperature_delta":
                value = _native_delta_to_f(numeric, unit)
            else:
                value = numeric
        available = value is not None
        if name in required and not available:
            reason = "missing_forecast_anchor" if name == "forecast_high" else "missing_required_feature"
            raise CandidateAbstention(reason, f"required feature {name!r} is missing")
        output[name] = value if available else math.nan
        output[f"{name}_available"] = 1.0 if available else 0.0
        output[f"{name}_missing"] = 0.0 if available else 1.0

    output.update(
        _source_health_features(
            source_diagnostics,
            required_sources=artifact["source_health_policy"]["required_sources"],
            allowed_states=set(artifact["source_health_policy"]["allowed_states"]),
        )
    )
    undeclared = sorted(set(artifact["feature_names"]) - set(output))
    if undeclared:
        raise ResidualArtifactError(
            "pipeline feature_names are not generated by the feature contract: "
            + ", ".join(undeclared)
        )
    return output


def gaussian_residual_density(
    mean_f: float,
    sigma_f: float,
    grid_f: Sequence[float],
) -> dict[float, float]:
    """Return a normalized Gaussian approximation on the declared F grid."""

    sigma_f = float(sigma_f)
    if not math.isfinite(mean_f) or not math.isfinite(sigma_f) or sigma_f <= 0:
        raise ValueError("Gaussian mean and sigma must be finite and sigma positive")
    weights = {}
    for value in grid_f:
        grid_value = float(value)
        z = (grid_value - float(mean_f)) / sigma_f
        weights[grid_value] = math.exp(-0.5 * z * z)
    density = normalize_density(weights)
    if not density:
        raise ValueError("Gaussian density has no mass on the artifact grid")
    return density


def truncate_at_printed_observed_high(
    density_f: Mapping[float, float],
    *,
    printed_high_native: Any,
    unit: str,
) -> tuple[dict[float, float], int | None, float | None]:
    """Apply only the settlement-valid floor implied by the printed daily high."""

    printed_high = _finite_float(printed_high_native)
    if printed_high is None:
        return normalize_density(density_f), None, None
    floor_bucket = round_half_up(printed_high)
    threshold_f = native_to_f(float(floor_bucket) - 0.5, unit)
    truncated = normalize_density(
        {
            float(value): (float(probability) if float(value) >= threshold_f else 0.0)
            for value, probability in density_f.items()
        }
    )
    if not truncated:
        raise ValueError("printed observed high lies above the artifact density grid")
    return truncated, floor_bucket, threshold_f


def simplex_temperature(
    probabilities: Mapping[str, float],
    temperature: float,
) -> dict[str, float]:
    """Apply the candidate's sole calibrator jointly to one probability simplex."""

    temperature = float(temperature)
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("simplex temperature must be positive")
    exponent = 1.0 / temperature
    transformed = {}
    for key, raw in probabilities.items():
        probability = float(raw)
        if not math.isfinite(probability) or probability < 0:
            raise ValueError("simplex probabilities must be finite and non-negative")
        transformed[str(key)] = probability**exponent if probability > 0 else 0.0
    total = sum(transformed.values())
    if total <= 0:
        raise ValueError("simplex has no positive probability mass")
    return {key: value / total for key, value in transformed.items()}


def _band_value(band: Mapping[str, Any], key: str) -> Any:
    aliases = {
        "bin_kind": ("kind",),
        "bin_value_c": ("value", "bin_value"),
        "bin_value_hi_c": ("value_hi", "bin_value_hi"),
    }
    if band.get(key) is not None:
        return band.get(key)
    for alias in aliases.get(key, ()):
        if band.get(alias) is not None:
            return band.get(alias)
    return None


def _band_key_value(value: Any) -> str:
    number = _finite_float(value)
    if number is None:
        return "unknown"
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return str(number).replace(".", "p")


def residual_band_key(band: Mapping[str, Any]) -> str:
    """Match the live variant-tape key contract without importing that adapter."""

    kind = str(_band_value(band, "bin_kind") or "eq").lower()
    value = _band_key_value(_band_value(band, "bin_value_c"))
    value_hi = _band_key_value(_band_value(band, "bin_value_hi_c"))
    if kind == "lte":
        return f"lte_{value}c"
    if kind == "gte":
        return f"gte_{value}c"
    if value_hi != "unknown" and value_hi != value:
        return f"eq_{value}_{value_hi}c"
    return f"eq_{value}c"


def _validated_band_partition(
    band_rows: Sequence[Mapping[str, Any]], unit: str
) -> list[tuple[Mapping[str, Any], str, float, float | None]]:
    if not isinstance(band_rows, Sequence) or not band_rows:
        raise ValueError("band_rows must be a non-empty sequence")
    intervals = []
    keys = set()
    for band in band_rows:
        if not isinstance(band, Mapping):
            raise ValueError("every band row must be a mapping")
        kind = str(_band_value(band, "bin_kind") or "eq").lower()
        if kind not in {"eq", "lte", "gte"}:
            raise ValueError(f"unsupported band kind {kind!r}")
        value = _finite_float(_band_value(band, "bin_value_c"))
        value_hi = _finite_float(_band_value(band, "bin_value_hi_c"))
        if value is None:
            raise ValueError("every band must declare a numeric value")
        if value_hi is not None and value_hi < value:
            raise ValueError("band upper value cannot be below its lower value")
        low_native, high_native = bucket_interval_native(kind, value, value_hi)
        low_f, high_f = native_interval_to_f(low_native, high_native, unit)
        key = residual_band_key(band)
        if key in keys:
            raise ValueError(f"duplicate band key {key!r}")
        keys.add(key)
        intervals.append((band, key, low_f, high_f))

    intervals.sort(key=lambda row: -math.inf if row[2] is None else row[2])
    if intervals[0][2] is not None or intervals[-1][3] is not None:
        raise ValueError("market bands must include lower and upper tail partitions")
    for previous, current in zip(intervals, intervals[1:]):
        previous_high = previous[3]
        current_low = current[2]
        if previous_high is None or current_low is None or not math.isclose(
            previous_high, current_low, rel_tol=0.0, abs_tol=1e-9
        ):
            raise ValueError("market bands must be contiguous and non-overlapping")
    return intervals


def project_density_to_bands(
    density_f: Mapping[float, float],
    *,
    unit: str,
    band_rows: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    """Project one canonical-F density into an exact native-unit partition."""

    intervals = _validated_band_partition(band_rows, unit)
    probabilities = {}
    for band, key, _low_f, _high_f in intervals:
        probabilities[key] = band_probability_from_density(
            density_f,
            unit,
            _band_value(band, "bin_kind") or "eq",
            _band_value(band, "bin_value_c"),
            value_hi=_band_value(band, "bin_value_hi_c"),
        )
    total = sum(probabilities.values())
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"native band partition captured probability mass {total!r}, not 1")
    return probabilities


def _abstained(reason: str, detail: str) -> dict[str, Any]:
    return {
        "status": "skipped",
        "failure_reason": f"abstain_{reason}",
        "failure_detail": detail,
        "prediction_mode": PREDICTION_MODE,
    }


def _failed(reason: str, detail: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "failure_reason": reason,
        "failure_detail": detail,
        "prediction_mode": PREDICTION_MODE,
    }


def predict_residual_distribution_v1(
    *,
    artifact: Mapping[str, Any] | None,
    feature_vector: Mapping[str, Any] | None,
    source_diagnostics: Sequence[Mapping[str, Any]] | None = None,
    market_id: str,
    unit: str | None = None,
    band_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Score one input with no fallback, incumbent blend, or hidden correction.

    Input incompatibility is a named, non-countable abstention.  Corrupt model
    state, malformed bands, and inference errors are failures.
    """

    market_id = str(market_id or "").strip()
    spec = REGISTRY.get(market_id)
    if spec is None:
        return _abstained("unknown_market", f"market_id {market_id!r} is not registered")
    expected_unit = str(spec.display_unit).upper()
    declared_units = [value for value in (unit,) if value not in (None, "")]
    if isinstance(feature_vector, Mapping):
        declared_units.extend(
            value
            for value in (feature_vector.get("display_unit"), feature_vector.get("unit"))
            if value not in (None, "")
        )
    if any(str(value).strip().upper() != expected_unit for value in declared_units):
        return _abstained(
            "unit_mismatch",
            f"market {market_id!r} requires {expected_unit}; declared units={declared_units!r}",
        )

    try:
        normalized_artifact = validate_artifact(artifact)
    except Exception as exc:  # Artifact validation must never reach another model.
        return _failed("invalid_artifact", f"{type(exc).__name__}: {exc}")

    try:
        canonical = canonical_candidate_features(
            artifact=normalized_artifact,
            feature_vector=feature_vector or {},
            source_diagnostics=source_diagnostics,
            market_id=market_id,
            unit=expected_unit,
        )
    except CandidateAbstention as exc:
        return _abstained(exc.reason, exc.detail)
    except Exception as exc:
        return _failed("invalid_artifact", f"{type(exc).__name__}: {exc}")

    try:
        feature_names = normalized_artifact["feature_names"]
        frame = pd.DataFrame(
            [{name: canonical[name] for name in feature_names}],
            columns=feature_names,
        )
        residuals = normalized_artifact["pipeline"].predict(frame)
        if len(residuals) != 1:
            raise ValueError("Ridge pipeline returned an unexpected prediction shape")
        residual_f = _finite_float(residuals[0])
        anchor_f = _finite_float(canonical.get("forecast_high"))
        if residual_f is None or anchor_f is None:
            raise ValueError("Ridge pipeline returned a non-finite residual")
        mean_f = anchor_f + residual_f
        sigma_f = float(normalized_artifact["residual_sigma_f"])
        grid_f = canonical_grid_f(
            normalized_artifact["grid_low_f"],
            normalized_artifact["grid_high_f"],
            normalized_artifact["grid_step_f"],
        )
        density = gaussian_residual_density(mean_f, sigma_f, grid_f)
        density, floor_bucket, floor_threshold_f = truncate_at_printed_observed_high(
            density,
            printed_high_native=(feature_vector or {}).get("high_so_far"),
            unit=expected_unit,
        )
        raw_probabilities = project_density_to_bands(
            density,
            unit=expected_unit,
            band_rows=band_rows,
        )
        temperature = normalized_artifact["calibration"]["temperature"]
        probabilities = simplex_temperature(raw_probabilities, temperature)
    except ValueError as exc:
        detail = f"{type(exc).__name__}: {exc}"
        if "band" in str(exc).lower() or "partition" in str(exc).lower():
            return _failed("invalid_band_partition", detail)
        return _failed("inference_failed", detail)
    except Exception as exc:  # sklearn/pandas errors are contained in this variant.
        return _failed("inference_failed", f"{type(exc).__name__}: {exc}")

    return {
        "status": "predicted",
        "failure_reason": None,
        "failure_detail": "",
        "prediction_mode": PREDICTION_MODE,
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "model_version": normalized_artifact.get("model_version") or ARTIFACT_SCHEMA_VERSION,
        "probabilities": probabilities,
        "mean_f": mean_f,
        "residual_f": residual_f,
        "sigma_f": sigma_f,
        "calibration_temperature": temperature,
        "printed_observed_floor_bucket": floor_bucket,
        "printed_observed_floor_threshold_f": floor_threshold_f,
    }
