"""Compatibility registry for no-market extra-location labels."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import config_path, data_path
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("no_market_extra_location_registry")
REPORT_SCHEMA_VERSION = schema_version("extra_location_compatibility_report")
DEFAULT_REGISTRY_PATH = config_path("no_market_extra_locations.json")
DEFAULT_JSON_OUT = data_path("backtest", "no_market_extra_location_compatibility.json")
DEFAULT_REPORT_OUT = data_path("backtest", "no_market_extra_location_compatibility_report.md")

DEFAULT_MIN_LABELED_DAYS = 60
DEFAULT_MIN_FORECAST_HISTORY_DAYS = 45
DEFAULT_MIN_OBSERVATION_DAYS = 60

PASS = "PASS"
SHADOW_ONLY = "SHADOW_ONLY"
BLOCKED = "BLOCKED"

VALID_TARGET_DEFINITIONS = {
    "daily_high_temperature",
    "daily_max_temperature",
    "highest_daily_temperature",
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _location_id(row: dict[str, Any]) -> str:
    return str(row.get("location_id") or row.get("id") or "").strip()


def _station_id(row: dict[str, Any]) -> str:
    station = row.get("station") or {}
    settlement = row.get("settlement") or {}
    return str(
        row.get("station_id")
        or station.get("station_id")
        or settlement.get("station_id")
        or ""
    ).strip()


def _source_ids(row: dict[str, Any]) -> list[str]:
    value = row.get("source_ids")
    if value is None:
        value = (row.get("sources") or {}).get("ids")
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _coordinates(row: dict[str, Any]) -> dict[str, Any]:
    coords = row.get("coordinates") or {}
    return {
        "lat": row.get("lat", coords.get("lat")),
        "lon": row.get("lon", coords.get("lon")),
        "elevation_m": row.get("elevation_m", coords.get("elevation_m")),
    }


def _target_definition(row: dict[str, Any]) -> str:
    return str(row.get("target_definition") or row.get("target") or "").strip()


def _grade(ok: bool, reason: str, *, severity: str = "required") -> dict[str, Any]:
    return {
        "ok": bool(ok),
        "severity": severity,
        "reason": reason,
    }


def _coverage_status(days: int, minimum: int) -> str:
    return PASS if days >= minimum else SHADOW_ONLY


def grade_location(
    row: dict[str, Any],
    *,
    min_labeled_days: int = DEFAULT_MIN_LABELED_DAYS,
    min_forecast_history_days: int = DEFAULT_MIN_FORECAST_HISTORY_DAYS,
    min_observation_days: int = DEFAULT_MIN_OBSERVATION_DAYS,
) -> dict[str, Any]:
    """Return a machine-readable compatibility grade for one extra location."""

    location_id = _location_id(row)
    coords = _coordinates(row)
    target_definition = _target_definition(row)
    station_id = _station_id(row)
    source_ids = _source_ids(row)
    timezone_name = str(row.get("timezone") or "").strip()
    unit = str(row.get("unit") or row.get("market_unit") or "").strip().upper()
    cutoff = str(row.get("cutoff_policy") or row.get("cutoff") or "").strip()
    labeled_days = _as_int(row.get("independent_labeled_days") or row.get("labeled_days"))
    forecast_days = _as_int(row.get("forecast_history_days"))
    observation_days = _as_int(row.get("observation_days") or row.get("source_observation_days"))
    station_stability = str(row.get("station_stability") or "").strip().lower()
    diagnostic_only = bool(row.get("diagnostic_only"))

    critical = []
    shadow = []
    grades = {
        "settlement_label_compatibility": _grade(
            bool(target_definition in VALID_TARGET_DEFINITIONS and unit),
            "target definition must be daily high temperature with an explicit unit",
        ),
        "forecast_history_coverage": _grade(
            forecast_days >= int(min_forecast_history_days),
            f"forecast history days {forecast_days} / {int(min_forecast_history_days)}",
            severity="coverage",
        ),
        "observation_source_coverage": _grade(
            observation_days >= int(min_observation_days) and labeled_days >= int(min_labeled_days),
            (
                f"observation days {observation_days} / {int(min_observation_days)}, "
                f"labeled days {labeled_days} / {int(min_labeled_days)}"
            ),
            severity="coverage",
        ),
        "station_stability": _grade(
            station_stability in {"stable", "verified", "low_revision_risk"},
            "station stability must be stable, verified, or low_revision_risk",
        ),
        "unit_timezone_cutoff_compatibility": _grade(
            bool(timezone_name and unit in {"C", "F"} and cutoff),
            "timezone, unit, and cutoff policy are required",
        ),
        "climate_domain_similarity": _grade(
            row.get("climate_similarity_class") not in {"unknown", None, ""},
            "climate similarity class must be explicit",
            severity="advisory",
        ),
        "station_provenance": _grade(
            bool(station_id and source_ids),
            "station id and source ids are required",
        ),
        "coordinates": _grade(
            _as_float(coords.get("lat")) is not None
            and _as_float(coords.get("lon")) is not None
            and _as_float(coords.get("elevation_m")) is not None,
            "latitude, longitude, and elevation are required",
        ),
    }

    for name, grade in grades.items():
        if grade["ok"]:
            continue
        reason = f"{name}: {grade['reason']}"
        if grade["severity"] == "coverage":
            shadow.append(reason)
        else:
            critical.append(reason)

    if diagnostic_only:
        shadow.append("location is explicitly diagnostic_only")

    if critical:
        status = BLOCKED
    elif shadow:
        status = SHADOW_ONLY
    else:
        status = PASS

    return {
        "location_id": location_id,
        "name": row.get("name") or row.get("city") or location_id,
        "status": status,
        "training_eligible": status == PASS,
        "diagnostic_only": diagnostic_only or status != PASS,
        "reasons": critical + shadow,
        "grades": grades,
        "provenance": {
            "station_id": station_id,
            "source_ids": source_ids,
            "timezone": timezone_name,
            "unit": unit,
            "cutoff_policy": cutoff,
            "target_definition": target_definition,
            "coordinates": coords,
            "coastal": bool(row.get("coastal", False)),
            "provenance_notes": row.get("provenance_notes") or row.get("notes") or [],
        },
        "evidence": {
            "independent_labeled_days": labeled_days,
            "forecast_history_days": forecast_days,
            "observation_days": observation_days,
            "target_season_coverage": row.get("target_season_coverage") or [],
        },
        "similarity": {
            "climate_normal": _as_float(row.get("climate_normal")),
            "climate_std": _as_float(row.get("climate_std")),
            "climate_similarity_class": row.get("climate_similarity_class"),
            "source_reliability_prior": _as_float(row.get("source_reliability_prior")),
            "forecast_error_mae": _as_float(row.get("forecast_error_mae")),
        },
        "raw": dict(row),
    }


def empty_registry(path: str | Path | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "path": str(path) if path else None,
        "exists": False,
        "locations": [],
    }


def load_registry(path: str | Path = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return empty_registry(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported no-market extra-location registry schema {payload.get('schema_version')!r}"
        )
    output = dict(payload)
    output["path"] = str(path)
    output["exists"] = True
    output["locations"] = list(payload.get("locations") or [])
    return output


def build_compatibility_report(
    registry: dict[str, Any],
    *,
    min_labeled_days: int = DEFAULT_MIN_LABELED_DAYS,
    min_forecast_history_days: int = DEFAULT_MIN_FORECAST_HISTORY_DAYS,
    min_observation_days: int = DEFAULT_MIN_OBSERVATION_DAYS,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    rows = [
        grade_location(
            row,
            min_labeled_days=min_labeled_days,
            min_forecast_history_days=min_forecast_history_days,
            min_observation_days=min_observation_days,
        )
        for row in registry.get("locations") or []
    ]
    counts = {PASS: 0, SHADOW_ONLY: 0, BLOCKED: 0}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    training_ids = [row["location_id"] for row in rows if row["training_eligible"]]
    shadow_ids = [row["location_id"] for row in rows if row["status"] == SHADOW_ONLY]
    blocked_ids = [row["location_id"] for row in rows if row["status"] == BLOCKED]
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "registry_schema_version": registry.get("schema_version"),
        "generated_at_utc": generated_at_utc or utc_iso(),
        "status": BLOCKED if blocked_ids else (SHADOW_ONLY if shadow_ids else PASS),
        "registry_path": registry.get("path"),
        "summary": {
            "location_count": len(rows),
            "training_eligible_location_count": len(training_ids),
            "shadow_only_location_count": len(shadow_ids),
            "blocked_location_count": len(blocked_ids),
            "independent_location_days": sum(
                int((row.get("evidence") or {}).get("independent_labeled_days") or 0)
                for row in rows
                if row.get("training_eligible")
            ),
            "diagnostic_location_days": sum(
                int((row.get("evidence") or {}).get("independent_labeled_days") or 0)
                for row in rows
                if not row.get("training_eligible")
            ),
            "status_counts": counts,
        },
        "minimums": {
            "independent_labeled_days": int(min_labeled_days),
            "forecast_history_days": int(min_forecast_history_days),
            "observation_days": int(min_observation_days),
        },
        "training_eligible_location_ids": training_ids,
        "shadow_only_location_ids": shadow_ids,
        "blocked_location_ids": blocked_ids,
        "locations": rows,
    }


def training_eligible_ids(report: dict[str, Any]) -> set[str]:
    return set(report.get("training_eligible_location_ids") or [])


def location_status_map(report: dict[str, Any]) -> dict[str, str]:
    return {
        row.get("location_id"): row.get("status")
        for row in report.get("locations") or []
        if row.get("location_id")
    }


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def _location_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    output = []
    for row in rows:
        evidence = row.get("evidence") or {}
        output.append([
            row.get("location_id"),
            row.get("status"),
            row.get("training_eligible"),
            evidence.get("independent_labeled_days"),
            evidence.get("forecast_history_days"),
            evidence.get("observation_days"),
            "; ".join(row.get("reasons") or []) or "passes compatibility gate",
        ])
    return output


def render_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# No-Market Extra-Location Compatibility",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Locations", summary.get("location_count", 0)],
            ["Training eligible", summary.get("training_eligible_location_count", 0)],
            ["Shadow only", summary.get("shadow_only_location_count", 0)],
            ["Blocked", summary.get("blocked_location_count", 0)],
            ["Training independent location-days", summary.get("independent_location_days", 0)],
            ["Diagnostic location-days", summary.get("diagnostic_location_days", 0)],
        ],
    )
    lines += ["", "## Minimums", ""]
    lines += markdown_table(
        ["Requirement", "Days"],
        [
            [key, value]
            for key, value in (payload.get("minimums") or {}).items()
        ],
    )
    lines += ["", "## Locations", ""]
    lines += markdown_table(
        [
            "Location",
            "Status",
            "Training Eligible",
            "Labeled Days",
            "Forecast Days",
            "Observation Days",
            "Reasons",
        ],
        _location_rows(payload.get("locations") or []),
    )
    return "\n".join(lines) + "\n"


def write_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Grade no-market extra locations before shadow training."
    )
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY_PATH))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--min-labeled-days", type=int, default=DEFAULT_MIN_LABELED_DAYS)
    parser.add_argument("--min-forecast-history-days", type=int, default=DEFAULT_MIN_FORECAST_HISTORY_DAYS)
    parser.add_argument("--min-observation-days", type=int, default=DEFAULT_MIN_OBSERVATION_DAYS)
    return parser


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = build_parser()
    args = parser.parse_args(argv)
    registry = load_registry(args.registry)
    payload = build_compatibility_report(
        registry,
        min_labeled_days=args.min_labeled_days,
        min_forecast_history_days=args.min_forecast_history_days,
        min_observation_days=args.min_observation_days,
    )
    json_path = write_json(args.json_out, payload)
    report_path = write_report(args.report_out, payload)
    print(f"No-market extra-location compatibility: {payload['status']}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return payload


if __name__ == "__main__":
    main()
