"""Similarity-weighted partial pooling for no-market extra locations."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import config_path, data_path
from weather.reporting.extra_location_registry import (
    build_compatibility_report,
    load_registry,
)
from weather.reporting.formatting import fmt_num, markdown_table
from weather.schema_registry import schema_version


SIMILARITY_SCHEMA_VERSION = schema_version("location_similarity_features")
POOLING_SCHEMA_VERSION = schema_version("location_similarity_partial_pooling")
DEFAULT_JSON_OUT = data_path("backtest", "location_similarity_partial_pooling.json")
DEFAULT_REPORT_OUT = data_path("backtest", "location_similarity_partial_pooling_report.md")

DEFAULT_TARGET_LOCAL_WEIGHT = 0.70
DEFAULT_MIN_SIMILARITY = 0.15


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _nested(row: dict[str, Any], *keys: str) -> Any:
    value: Any = row
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def location_id(row: dict[str, Any]) -> str:
    return str(row.get("location_id") or row.get("id") or "").strip()


def _lat(row: dict[str, Any]) -> float | None:
    return _float(row.get("lat") or _nested(row, "coordinates", "lat") or _nested(row, "provenance", "coordinates", "lat"))


def _lon(row: dict[str, Any]) -> float | None:
    return _float(row.get("lon") or _nested(row, "coordinates", "lon") or _nested(row, "provenance", "coordinates", "lon"))


def _elevation(row: dict[str, Any]) -> float | None:
    return _float(
        row.get("elevation_m")
        or _nested(row, "coordinates", "elevation_m")
        or _nested(row, "provenance", "coordinates", "elevation_m")
    )


def _similarity_value(row: dict[str, Any], key: str) -> float | None:
    return _float(row.get(key) or _nested(row, "similarity", key) or _nested(row, "raw", key))


def _coastal(row: dict[str, Any]) -> bool | None:
    value = row.get("coastal")
    if value is None:
        value = _nested(row, "provenance", "coastal")
    if value is None:
        value = _nested(row, "raw", "coastal")
    if value is None:
        return None
    return bool(value)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    return 2.0 * radius_km * math.asin(min(1.0, math.sqrt(a)))


def similarity_features(target: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    target_lat = _lat(target)
    target_lon = _lon(target)
    extra_lat = _lat(extra)
    extra_lon = _lon(extra)
    distance_km = None
    if None not in (target_lat, target_lon, extra_lat, extra_lon):
        distance_km = haversine_km(float(target_lat), float(target_lon), float(extra_lat), float(extra_lon))

    target_elev = _elevation(target)
    extra_elev = _elevation(extra)
    elevation_gap_m = None
    if None not in (target_elev, extra_elev):
        elevation_gap_m = abs(float(target_elev) - float(extra_elev))

    target_normal = _similarity_value(target, "climate_normal")
    extra_normal = _similarity_value(extra, "climate_normal")
    climate_normal_gap = None
    if None not in (target_normal, extra_normal):
        climate_normal_gap = abs(float(target_normal) - float(extra_normal))

    target_std = _similarity_value(target, "climate_std")
    extra_std = _similarity_value(extra, "climate_std")
    climate_std_gap = None
    if None not in (target_std, extra_std):
        climate_std_gap = abs(float(target_std) - float(extra_std))

    target_reliability = _similarity_value(target, "source_reliability_prior")
    extra_reliability = _similarity_value(extra, "source_reliability_prior")
    reliability_gap = None
    if None not in (target_reliability, extra_reliability):
        reliability_gap = abs(float(target_reliability) - float(extra_reliability))

    target_error = _similarity_value(target, "forecast_error_mae")
    extra_error = _similarity_value(extra, "forecast_error_mae")
    forecast_error_gap = None
    if None not in (target_error, extra_error):
        forecast_error_gap = abs(float(target_error) - float(extra_error))

    coastal_target = _coastal(target)
    coastal_extra = _coastal(extra)
    coastal_match = coastal_target is not None and coastal_extra is not None and coastal_target == coastal_extra

    penalties = []
    if distance_km is not None:
        penalties.append(min(2.0, distance_km / 2500.0))
    if elevation_gap_m is not None:
        penalties.append(min(1.5, elevation_gap_m / 1000.0))
    if climate_normal_gap is not None:
        penalties.append(min(2.0, climate_normal_gap / 25.0))
    if climate_std_gap is not None:
        penalties.append(min(1.0, climate_std_gap / 15.0))
    if reliability_gap is not None:
        penalties.append(min(1.0, reliability_gap))
    if forecast_error_gap is not None:
        penalties.append(min(1.0, forecast_error_gap / 8.0))
    if coastal_target is not None and coastal_extra is not None and not coastal_match:
        penalties.append(0.35)
    if not penalties:
        score = 0.0
    else:
        score = math.exp(-sum(penalties) / len(penalties))

    return {
        "schema_version": SIMILARITY_SCHEMA_VERSION,
        "target_location_id": location_id(target),
        "extra_location_id": location_id(extra),
        "distance_km": distance_km,
        "elevation_gap_m": elevation_gap_m,
        "climate_normal_gap": climate_normal_gap,
        "climate_std_gap": climate_std_gap,
        "coastal_match": coastal_match,
        "source_reliability_gap": reliability_gap,
        "forecast_error_mae_gap": forecast_error_gap,
        "similarity_score": max(0.0, min(1.0, score)),
    }


def build_similarity_table(
    target_locations: list[dict[str, Any]],
    extra_locations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for target in target_locations:
        for extra in extra_locations:
            if location_id(target) and location_id(target) == location_id(extra):
                continue
            rows.append(similarity_features(target, extra))
    rows.sort(key=lambda row: (row["target_location_id"], -row["similarity_score"], row["extra_location_id"]))
    return rows


def pooling_weights(
    similarity_rows: list[dict[str, Any]],
    *,
    target_location_id: str,
    target_local_weight: float = DEFAULT_TARGET_LOCAL_WEIGHT,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> dict[str, Any]:
    selected = [
        row for row in similarity_rows
        if row.get("target_location_id") == target_location_id
        and float(row.get("similarity_score") or 0.0) >= float(min_similarity)
    ]
    total = sum(float(row.get("similarity_score") or 0.0) for row in selected)
    extra_budget = max(0.0, min(1.0, 1.0 - float(target_local_weight)))
    weights = {}
    for row in selected:
        extra_id = row.get("extra_location_id")
        if total > 0 and extra_id:
            weights[extra_id] = extra_budget * float(row.get("similarity_score") or 0.0) / total
    fallback = not weights
    return {
        "target_location_id": target_location_id,
        "target_local_weight": 1.0 if fallback else float(target_local_weight),
        "extra_weight_budget": 0.0 if fallback else extra_budget,
        "min_similarity": float(min_similarity),
        "fallback_to_target_only": fallback,
        "extra_weights": dict(sorted(weights.items())),
    }


def blend_prediction(
    target_prediction: float | None,
    extra_predictions: dict[str, float],
    weights: dict[str, Any],
) -> dict[str, Any]:
    if target_prediction is None:
        return {
            "prediction": None,
            "fallback_to_target_only": True,
            "reason": "missing target-local prediction",
            "attribution": [],
        }
    prediction = float(target_prediction) * float(weights.get("target_local_weight") or 0.0)
    attribution = [{
        "location_id": weights.get("target_location_id"),
        "weight": float(weights.get("target_local_weight") or 0.0),
        "prediction": float(target_prediction),
        "contribution": float(target_prediction) * float(weights.get("target_local_weight") or 0.0),
        "source": "target_local",
    }]
    for extra_id, weight in (weights.get("extra_weights") or {}).items():
        if extra_id not in extra_predictions:
            continue
        contribution = float(weight) * float(extra_predictions[extra_id])
        prediction += contribution
        attribution.append({
            "location_id": extra_id,
            "weight": float(weight),
            "prediction": float(extra_predictions[extra_id]),
            "contribution": contribution,
            "source": "extra_location",
        })
    return {
        "prediction": prediction,
        "fallback_to_target_only": bool(weights.get("fallback_to_target_only")),
        "reason": "target-local fallback" if weights.get("fallback_to_target_only") else "similarity-weighted partial pooling",
        "attribution": attribution,
    }


def build_payload(
    target_locations: list[dict[str, Any]],
    extra_locations: list[dict[str, Any]],
    *,
    target_local_weight: float = DEFAULT_TARGET_LOCAL_WEIGHT,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    similarity_rows = build_similarity_table(target_locations, extra_locations)
    targets = sorted({location_id(row) for row in target_locations if location_id(row)})
    weights = [
        pooling_weights(
            similarity_rows,
            target_location_id=target_id,
            target_local_weight=target_local_weight,
            min_similarity=min_similarity,
        )
        for target_id in targets
    ]
    return {
        "schema_version": POOLING_SCHEMA_VERSION,
        "similarity_schema_version": SIMILARITY_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "summary": {
            "target_location_count": len(targets),
            "extra_location_count": len({location_id(row) for row in extra_locations if location_id(row)}),
            "similarity_pair_count": len(similarity_rows),
            "fallback_target_count": sum(1 for row in weights if row.get("fallback_to_target_only")),
        },
        "policy": {
            "target_local_weight": float(target_local_weight),
            "min_similarity": float(min_similarity),
            "selection_basis": "blocked target-market validation chooses pooling strength",
        },
        "similarity_rows": similarity_rows,
        "pooling_weights": weights,
    }


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def render_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Location-Similarity Partial Pooling",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Target locations", summary.get("target_location_count", 0)],
            ["Extra locations", summary.get("extra_location_count", 0)],
            ["Similarity pairs", summary.get("similarity_pair_count", 0)],
            ["Target-only fallbacks", summary.get("fallback_target_count", 0)],
        ],
    )
    lines += ["", "## Weights", ""]
    lines += markdown_table(
        ["Target", "Target Weight", "Extra Weights", "Fallback"],
        [
            [
                row.get("target_location_id"),
                fmt_num(row.get("target_local_weight")),
                ", ".join(f"{key}={value:.3f}" for key, value in (row.get("extra_weights") or {}).items()) or "-",
                row.get("fallback_to_target_only"),
            ]
            for row in payload.get("pooling_weights") or []
        ],
    )
    lines += ["", "## Similarity Pairs", ""]
    lines += markdown_table(
        ["Target", "Extra", "Score", "Distance km", "Climate Gap", "Coastal Match"],
        [
            [
                row.get("target_location_id"),
                row.get("extra_location_id"),
                fmt_num(row.get("similarity_score")),
                fmt_num(row.get("distance_km")),
                fmt_num(row.get("climate_normal_gap")),
                row.get("coastal_match"),
            ]
            for row in payload.get("similarity_rows") or []
        ],
    )
    return "\n".join(lines) + "\n"


def write_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def _locations_from_compatibility(report: dict[str, Any], *, training_only: bool) -> list[dict[str, Any]]:
    rows = []
    for row in report.get("locations") or []:
        if training_only and not row.get("training_eligible"):
            continue
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(
        description="Build no-market extra-location similarity weights."
    )
    parser.add_argument("--target-locations-json", default="", help="JSON file containing target location rows.")
    parser.add_argument("--extra-location-registry", default=str(config_path("no_market_extra_locations.json")))
    parser.add_argument("--include-shadow-only", action="store_true")
    parser.add_argument("--target-local-weight", type=float, default=DEFAULT_TARGET_LOCAL_WEIGHT)
    parser.add_argument("--min-similarity", type=float, default=DEFAULT_MIN_SIMILARITY)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    args = parser.parse_args(argv)

    targets = []
    if args.target_locations_json:
        target_payload = json.loads(Path(args.target_locations_json).read_text(encoding="utf-8"))
        targets = target_payload.get("locations") if isinstance(target_payload, dict) else target_payload
        targets = list(targets or [])
    registry = load_registry(args.extra_location_registry)
    compatibility = build_compatibility_report(registry)
    extras = _locations_from_compatibility(
        compatibility,
        training_only=not args.include_shadow_only,
    )
    payload = build_payload(
        targets,
        extras,
        target_local_weight=args.target_local_weight,
        min_similarity=args.min_similarity,
    )
    json_path = write_json(args.json_out, payload)
    report_path = write_report(args.report_out, payload)
    print(f"Location-similarity partial pooling: {payload['summary']['similarity_pair_count']} pair(s)")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return payload


if __name__ == "__main__":
    main()
