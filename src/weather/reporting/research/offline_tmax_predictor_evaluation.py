"""Leakage-safe offline evaluation of one forecast Tmax predictor family.

The evaluator deliberately refuses the continuous historical-forecast archive:
those rows do not have a real issuance timestamp and therefore cannot support a
point-in-time performance claim.  Every scored row comes from an explicit,
timezone-aware issue time strictly before a predeclared local cutoff, and is
joined to the configured Weather Underground daily settlement proxy.

This is research tooling only.  It does not collect data, mutate the mirror, or
change serving behavior.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from weather.io import write_json_atomic, write_text_atomic
from weather.market.market_registry import BUILTIN_SPECS, MarketSpec
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.schema_registry import schema_version
from weather.sources.daily_summary import celsius_high
from weather.units import native_to_c, to_float


SCHEMA_VERSION = schema_version("offline_tmax_predictor_evaluation")
FORBIDDEN_ISSUE_TIME_BASES = frozenset({"stitched_continuous_archive"})
DEFAULT_CUTOFF_LOCAL = "00:00"
DEFAULT_HOLDOUT_FRACTION = 0.20
DEFAULT_FOLDS = 4
DEFAULT_RIDGE_ALPHA = 1.0
DEFAULT_BOOTSTRAP_REPLICATES = 2_000
DEFAULT_BOOTSTRAP_SEED = 20_260_722

FAMILY_ALIASES = {
    "pressure": "pressure",
    "850_925": "pressure",
    "pressure850": "pressure850",
    "850": "pressure850",
    "850_only": "pressure850",
    "soil": "soil",
    "radiation": "radiation",
    "shortwave_cloud": "radiation",
    "smoke": "smoke",
    "aod": "smoke",
    "hrrr_smoke": "hrrr_smoke",
    "hrrr-smoke": "hrrr_smoke",
}

RAW_FIELDS_BY_FAMILY: dict[str, tuple[str, ...]] = {
    "pressure": (
        "temperature_925hpa",
        "temperature_850hpa",
        "geopotential_height_500hpa",
    ),
    "pressure850": ("temperature_850hpa",),
    "soil": (
        "soil_temperature_0cm",
        "soil_moisture_0_to_1cm",
    ),
    "radiation": (
        "shortwave_radiation",
        "direct_radiation",
        "diffuse_radiation",
        "cloud_cover",
        "low_cloud",
        "mid_cloud",
        "high_cloud",
    ),
    "smoke": (
        "aerosol_optical_depth",
        "aod",
        "smoke_aod",
        "pm2_5",
        "pm2_5_concentration",
        "smoke",
    ),
    "hrrr_smoke": (
        "hrrr_aerosol_optical_depth",
        "hrrr_smoke_mass_density_ug_m3",
    ),
}


def resolve_paths_outside_read_only_root(
    *,
    read_only_root: str | Path,
    paths: Mapping[str, str | Path],
) -> tuple[Path, dict[str, Path]]:
    """Resolve output paths and reject aliases into a read-only source tree.

    ``Path.resolve(strict=False)`` normalizes relative/``..`` paths and follows
    every existing symlink in the path.  Validating the fully resolved target,
    rather than its spelling, keeps scratch-only research tools from writing
    through an alias back into their supplied data mirror.
    """

    try:
        root = Path(read_only_root).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"cannot resolve read-only root {read_only_root!s}: {exc}") from exc
    if not root.is_dir():
        raise ValueError(f"read-only root is not a directory: {root}")

    resolved: dict[str, Path] = {}
    for label, raw_path in paths.items():
        try:
            target = Path(raw_path).expanduser().resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"cannot resolve {label} path {raw_path!s}: {exc}") from exc
        try:
            target.relative_to(root)
        except ValueError:
            pass
        else:
            raise ValueError(
                f"{label} resolves inside the supplied read-only root: "
                f"target={target}, read_only_root={root}"
            )
        for prior_label, prior in resolved.items():
            same_file = False
            if target.exists() and prior.exists():
                try:
                    same_file = target.samefile(prior)
                except OSError:
                    same_file = False
            if target == prior or same_file:
                raise ValueError(
                    f"{label} collides with {prior_label} after path resolution: "
                    f"target={target}, prior={prior}"
                )
        resolved[label] = target
    return root, resolved

FEATURES_BY_FAMILY: dict[str, tuple[str, ...]] = {
    "pressure": (
        "temperature_925_mean_c",
        "temperature_925_max_c",
        "temperature_850_mean_c",
        "temperature_850_max_c",
        "lapse_925_minus_850_mean_c",
        "surface_minus_925_mean_c",
        "surface_minus_850_mean_c",
    ),
    "pressure850": (
        "temperature_850_mean_c",
        "temperature_850_max_c",
        "surface_minus_850_mean_c",
    ),
    "soil": (
        "soil_temperature_mean_c",
        "soil_temperature_max_c",
        "soil_moisture_mean",
        "soil_moisture_min",
        "soil_moisture_max",
        "surface_minus_soil_mean_c",
    ),
    "radiation": (
        "shortwave_sum",
        "shortwave_max",
        "direct_sum",
        "diffuse_sum",
        "direct_fraction",
        "cloud_cover_mean",
        "cloud_cover_max",
    ),
    "smoke": (
        "aod_mean",
        "pm2_5_mean",
        "aod_available",
        "pm2_5_available",
    ),
    "hrrr_smoke": (
        "hrrr_aerosol_optical_depth_mean",
        "hrrr_aerosol_optical_depth_max",
        "hrrr_smoke_mass_density_log1p_ug_m3_mean",
        "hrrr_smoke_mass_density_log1p_ug_m3_max",
    ),
}


@dataclass(frozen=True)
class Thresholds:
    """Predeclared minimum support required to open the holdout."""

    min_markets: int = 4
    min_train_dates: int = 30
    min_validation_dates: int = 10
    min_holdout_dates: int = 14
    min_train_rows: int = 80
    min_validation_rows: int = 20
    min_holdout_rows: int = 30


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_family(value: str) -> str:
    family = FAMILY_ALIASES.get(str(value).strip().lower())
    if family is None:
        raise ValueError(f"unsupported predictor family: {value!r}")
    return family


def _parse_cutoff(value: str) -> time:
    try:
        parsed = time.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid local cutoff {value!r}; expected HH:MM[:SS]") from exc
    if parsed.tzinfo is not None:
        raise ValueError("local cutoff must not contain a timezone offset")
    return parsed


def _parse_aware_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _finite_float(value: Any) -> float | None:
    number = to_float(value)
    if number is None or not math.isfinite(float(number)):
        return None
    return float(number)


def _mean(values: Iterable[float]) -> float | None:
    values = [float(value) for value in values]
    return sum(values) / len(values) if values else None


def _forecast_temperature_c(row: Mapping[str, Any]) -> float | None:
    explicit = _finite_float(row.get("target_temp_c"))
    if explicit is not None:
        return explicit
    native = _finite_float(row.get("target_temp_native"))
    if native is None:
        native = _finite_float(row.get("target_temp"))
    return native_to_c(native, row.get("temperature_unit") or "C", digits=None)


def _field_temperature_c(row: Mapping[str, Any], field: str) -> float | None:
    return native_to_c(
        _finite_float(row.get(field)),
        row.get("temperature_unit") or "C",
        digits=None,
    )


def _nonblank_field_counts(
    rows: Iterable[Mapping[str, Any]], fields: Sequence[str]
) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        for field in fields:
            if _finite_float(row.get(field)) is not None:
                counts[field] += 1
    return {field: int(counts[field]) for field in fields}


def _has_family_value(row: Mapping[str, Any], family: str) -> bool:
    return any(_finite_float(row.get(field)) is not None for field in RAW_FIELDS_BY_FAMILY[family])


def _temperature_series(rows: Sequence[Mapping[str, Any]], field: str) -> list[float]:
    output = []
    for row in rows:
        value = _field_temperature_c(row, field)
        if value is not None:
            output.append(float(value))
    return output


def _numeric_series(rows: Sequence[Mapping[str, Any]], field: str) -> list[float]:
    return [
        value
        for row in rows
        if (value := _finite_float(row.get(field))) is not None
    ]


def _pressure_features(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, float] | None, list[str]]:
    t925 = _temperature_series(rows, "temperature_925hpa")
    t850 = _temperature_series(rows, "temperature_850hpa")
    paired_pressure = []
    surface_925 = []
    surface_850 = []
    for row in rows:
        value_925 = _field_temperature_c(row, "temperature_925hpa")
        value_850 = _field_temperature_c(row, "temperature_850hpa")
        surface = _forecast_temperature_c(row)
        if value_925 is not None and value_850 is not None:
            paired_pressure.append(value_925 - value_850)
        if surface is not None and value_925 is not None:
            surface_925.append(surface - value_925)
        if surface is not None and value_850 is not None:
            surface_850.append(surface - value_850)
    missing = []
    if not t925:
        missing.append("temperature_925hpa")
    if not t850:
        missing.append("temperature_850hpa")
    if not paired_pressure:
        missing.append("paired_temperature_925hpa_850hpa")
    if not surface_925:
        missing.append("paired_surface_temperature_925hpa")
    if not surface_850:
        missing.append("paired_surface_temperature_850hpa")
    if missing:
        return None, missing
    return {
        "temperature_925_mean_c": float(_mean(t925)),
        "temperature_925_max_c": max(t925),
        "temperature_850_mean_c": float(_mean(t850)),
        "temperature_850_max_c": max(t850),
        "lapse_925_minus_850_mean_c": float(_mean(paired_pressure)),
        "surface_minus_925_mean_c": float(_mean(surface_925)),
        "surface_minus_850_mean_c": float(_mean(surface_850)),
    }, []


def _pressure850_features(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, float] | None, list[str]]:
    """Aggregate the single-level 850 hPa family used by the CFSv2 audit.

    The free CFSv2 variable time-series archive exposes temperature at 850 hPa
    but not 925 hPa.  Keeping this as a distinct family prevents a single-level
    experiment from silently changing the existing 850/925 pressure contract.
    """

    t850 = _temperature_series(rows, "temperature_850hpa")
    surface_850 = []
    for row in rows:
        value_850 = _field_temperature_c(row, "temperature_850hpa")
        surface = _forecast_temperature_c(row)
        if surface is not None and value_850 is not None:
            surface_850.append(surface - value_850)
    missing = []
    if not t850:
        missing.append("temperature_850hpa")
    if not surface_850:
        missing.append("paired_surface_temperature_850hpa")
    if missing:
        return None, missing
    return {
        "temperature_850_mean_c": float(_mean(t850)),
        "temperature_850_max_c": max(t850),
        "surface_minus_850_mean_c": float(_mean(surface_850)),
    }, []


def _soil_features(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, float] | None, list[str]]:
    soil_temperature = _temperature_series(rows, "soil_temperature_0cm")
    soil_moisture = _numeric_series(rows, "soil_moisture_0_to_1cm")
    surface_soil = []
    for row in rows:
        surface = _forecast_temperature_c(row)
        soil = _field_temperature_c(row, "soil_temperature_0cm")
        if surface is not None and soil is not None:
            surface_soil.append(surface - soil)
    missing = []
    if not soil_temperature:
        missing.append("soil_temperature_0cm")
    if not soil_moisture:
        missing.append("soil_moisture_0_to_1cm")
    if not surface_soil:
        missing.append("paired_surface_soil_temperature")
    if missing:
        return None, missing
    return {
        "soil_temperature_mean_c": float(_mean(soil_temperature)),
        "soil_temperature_max_c": max(soil_temperature),
        "soil_moisture_mean": float(_mean(soil_moisture)),
        "soil_moisture_min": min(soil_moisture),
        "soil_moisture_max": max(soil_moisture),
        "surface_minus_soil_mean_c": float(_mean(surface_soil)),
    }, []


def _radiation_features(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, float] | None, list[str]]:
    shortwave = _numeric_series(rows, "shortwave_radiation")
    direct = _numeric_series(rows, "direct_radiation")
    diffuse = _numeric_series(rows, "diffuse_radiation")
    cloud = _numeric_series(rows, "cloud_cover")
    required = {
        "shortwave_radiation": shortwave,
        "direct_radiation": direct,
        "diffuse_radiation": diffuse,
        "cloud_cover": cloud,
    }
    missing = [field for field, values in required.items() if not values]
    if missing:
        return None, missing
    total_direct_diffuse = sum(direct) + sum(diffuse)
    return {
        "shortwave_sum": sum(shortwave),
        "shortwave_max": max(shortwave),
        "direct_sum": sum(direct),
        "diffuse_sum": sum(diffuse),
        "direct_fraction": sum(direct) / total_direct_diffuse if total_direct_diffuse else 0.0,
        "cloud_cover_mean": float(_mean(cloud)),
        "cloud_cover_max": max(cloud),
    }, []


def _first_available_series(
    rows: Sequence[Mapping[str, Any]], fields: Sequence[str]
) -> tuple[list[float], str | None]:
    for field in fields:
        values = _numeric_series(rows, field)
        if values:
            return values, field
    return [], None


def _smoke_features(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, float] | None, list[str]]:
    aod, aod_field = _first_available_series(
        rows, ("aerosol_optical_depth", "aod", "smoke_aod")
    )
    pm25, pm25_field = _first_available_series(
        rows, ("pm2_5", "pm2_5_concentration", "smoke")
    )
    if not aod and not pm25:
        return None, ["aod_or_smoke_proxy"]
    return {
        "aod_mean": float(_mean(aod)) if aod else 0.0,
        "pm2_5_mean": float(_mean(pm25)) if pm25 else 0.0,
        "aod_available": float(aod_field is not None),
        "pm2_5_available": float(pm25_field is not None),
    }, []


def _hrrr_smoke_features(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, float] | None, list[str]]:
    """Aggregate the predeclared HRRR AOTK + smoke-mass pair honestly.

    HRRR ``MASSDEN`` is modeled near-surface smoke mass density, not PM2.5.
    Keeping distinct raw and feature names prevents this research adapter from
    implying a particulate-size-specific measurement that the GRIB field does
    not provide.
    """

    aotk = _numeric_series(rows, "hrrr_aerosol_optical_depth")
    smoke_mass = _numeric_series(rows, "hrrr_smoke_mass_density_ug_m3")
    missing = []
    if not aotk:
        missing.append("hrrr_aerosol_optical_depth")
    if not smoke_mass:
        missing.append("hrrr_smoke_mass_density_ug_m3")
    if any(value < 0.0 for value in aotk):
        missing.append("nonnegative_hrrr_aerosol_optical_depth")
    if any(value < 0.0 for value in smoke_mass):
        missing.append("nonnegative_hrrr_smoke_mass_density_ug_m3")
    if missing:
        return None, missing
    smoke_mass_log1p = [math.log1p(value) for value in smoke_mass]
    return {
        "hrrr_aerosol_optical_depth_mean": float(_mean(aotk)),
        "hrrr_aerosol_optical_depth_max": max(aotk),
        "hrrr_smoke_mass_density_log1p_ug_m3_mean": float(
            _mean(smoke_mass_log1p)
        ),
        "hrrr_smoke_mass_density_log1p_ug_m3_max": max(smoke_mass_log1p),
    }, []


def family_features(
    rows: Sequence[Mapping[str, Any]], family: str
) -> tuple[dict[str, float] | None, list[str]]:
    """Aggregate one issue's hourly rows into one predeclared feature family."""

    family = _canonical_family(family)
    if family == "pressure":
        return _pressure_features(rows)
    if family == "pressure850":
        return _pressure850_features(rows)
    if family == "soil":
        return _soil_features(rows)
    if family == "radiation":
        return _radiation_features(rows)
    if family == "hrrr_smoke":
        return _hrrr_smoke_features(rows)
    return _smoke_features(rows)


def _resolve_station_file(root: Path, station: str, suffix: Sequence[str]) -> Path:
    lower = root / station.lower()
    upper = root / station.upper()
    base = lower if lower.exists() or not upper.exists() else upper
    return base.joinpath(*suffix)


def _file_provenance(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "size_bytes": None, "mtime_utc": None}
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": int(stat.st_size),
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def _read_settlements(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    output = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            target_date = str(row.get("local_date") or "")[:10]
            high_c = celsius_high(row)
            if target_date and high_c is not None and math.isfinite(float(high_c)):
                output[target_date] = float(high_c)
    return output


def _group_rank(item: tuple[tuple[str, str, str, str], list[dict[str, str]]]) -> tuple[Any, ...]:
    key, _ = item
    _, issue_text, source, source_model = key
    parsed = _parse_aware_datetime(issue_text)
    return (
        parsed.astimezone(timezone.utc) if parsed is not None else datetime.min.replace(tzinfo=timezone.utc),
        source == "open_meteo_previous_runs",
        source,
        source_model,
    )


def load_market_rows(
    *,
    data_root: str | Path,
    spec: MarketSpec,
    family: str,
    cutoff_local: str = DEFAULT_CUTOFF_LOCAL,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Load one market without admitting issue-time-ambiguous archive rows."""

    family = _canonical_family(family)
    cutoff = _parse_cutoff(cutoff_local)
    data_root = Path(data_root)
    forecast_path = _resolve_station_file(
        data_root / "forecast_history", spec.icao, ("forecast_long.csv",)
    )
    settlement_path = _resolve_station_file(
        data_root / "wunderground", spec.icao, ("daily", "daily_summary.csv")
    )
    provenance = {
        "forecast_history": _file_provenance(forecast_path),
        "wu_daily_summary": _file_provenance(settlement_path),
    }
    audit: dict[str, Any] = {
        "market_id": spec.id,
        "station": spec.icao,
        "temperature_unit": spec.unit,
        "forecast_path": str(forecast_path),
        "settlement_path": str(settlement_path),
        "forecast_file_exists": forecast_path.exists(),
        "settlement_file_exists": settlement_path.exists(),
        "forecast_rows": 0,
        "forbidden_stitched_rows": 0,
        "forbidden_stitched_family_rows": 0,
        "rows_with_explicit_issue_time": 0,
        "rows_rejected_missing_or_naive_issue_time": 0,
        "rows_rejected_invalid_target_date": 0,
        "rows_rejected_at_or_after_cutoff": 0,
        "admissible_rows": 0,
        "admissible_family_rows": 0,
        "selected_baseline_dates": 0,
        "matched_settlement_dates": 0,
        "family_supported_dates": 0,
        "family_missing_dates": 0,
        "issue_time_basis_counts": {},
        "admissible_raw_field_nonblank_counts": {},
        "forbidden_raw_field_nonblank_counts": {},
        "first_selected_date": None,
        "last_selected_date": None,
        "provenance": provenance,
    }
    if not forecast_path.exists():
        return [], audit, []

    basis_counts = Counter()
    admissible_field_counts = Counter()
    forbidden_field_counts = Counter()
    groups: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    raw_fields = RAW_FIELDS_BY_FAMILY[family]
    with forecast_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            audit["forecast_rows"] += 1
            basis = str(row.get("issue_time_basis") or "").strip()
            basis_counts[basis or "<blank>"] += 1
            if basis in FORBIDDEN_ISSUE_TIME_BASES:
                audit["forbidden_stitched_rows"] += 1
                if _has_family_value(row, family):
                    audit["forbidden_stitched_family_rows"] += 1
                for field in raw_fields:
                    if _finite_float(row.get(field)) is not None:
                        forbidden_field_counts[field] += 1
                continue

            issue_text = str(row.get("issue_time") or "").strip()
            if issue_text:
                audit["rows_with_explicit_issue_time"] += 1
            issue_time = _parse_aware_datetime(issue_text)
            if issue_time is None:
                audit["rows_rejected_missing_or_naive_issue_time"] += 1
                continue
            target = _parse_date(row.get("target_date"))
            if target is None:
                audit["rows_rejected_invalid_target_date"] += 1
                continue
            cutoff_dt = datetime.combine(target, cutoff, tzinfo=spec.tz)
            if issue_time.astimezone(timezone.utc) >= cutoff_dt.astimezone(timezone.utc):
                audit["rows_rejected_at_or_after_cutoff"] += 1
                continue
            audit["admissible_rows"] += 1
            if _has_family_value(row, family):
                audit["admissible_family_rows"] += 1
            for field in raw_fields:
                if _finite_float(row.get(field)) is not None:
                    admissible_field_counts[field] += 1
            key = (
                target.isoformat(),
                issue_text,
                str(row.get("source") or ""),
                str(row.get("source_model") or ""),
            )
            groups[key].append(row)

    audit["issue_time_basis_counts"] = dict(sorted(basis_counts.items()))
    audit["admissible_raw_field_nonblank_counts"] = {
        field: int(admissible_field_counts[field]) for field in raw_fields
    }
    audit["forbidden_raw_field_nonblank_counts"] = {
        field: int(forbidden_field_counts[field]) for field in raw_fields
    }

    groups_by_date: dict[str, list[tuple[tuple[str, str, str, str], list[dict[str, str]]]]] = defaultdict(list)
    for item in groups.items():
        groups_by_date[item[0][0]].append(item)
    settlements = _read_settlements(settlement_path)
    experiment_rows: list[dict[str, Any]] = []
    date_support: list[dict[str, Any]] = []
    selected_dates = []
    for target_date, candidates in sorted(groups_by_date.items()):
        key, rows = max(candidates, key=_group_rank)
        _, issue_text, source, source_model = key
        baseline_values = [
            value
            for row in rows
            if (value := _forecast_temperature_c(row)) is not None
        ]
        if not baseline_values:
            continue
        selected_dates.append(target_date)
        baseline_high_c = max(baseline_values)
        settlement_high_c = settlements.get(target_date)
        features, missing = family_features(rows, family)
        support_row = {
            "market_id": spec.id,
            "station": spec.icao,
            "target_date": target_date,
            "selected_issue_time": issue_text,
            "issue_time_basis": str(rows[0].get("issue_time_basis") or ""),
            "source": source,
            "source_model": source_model,
            "hourly_rows": len(rows),
            "baseline_forecast_high_c": baseline_high_c,
            "settlement_available": settlement_high_c is not None,
            "family_supported": features is not None,
            "missing_family_fields": missing,
        }
        date_support.append(support_row)
        if settlement_high_c is None:
            continue
        experiment_rows.append({
            **support_row,
            "settlement_high_c": settlement_high_c,
            "baseline_residual_c": settlement_high_c - baseline_high_c,
            "features": features,
        })

    matched = [row for row in experiment_rows]
    supported = [row for row in matched if row["family_supported"]]
    audit["selected_baseline_dates"] = len(selected_dates)
    audit["matched_settlement_dates"] = len(matched)
    audit["family_supported_dates"] = len(supported)
    audit["family_missing_dates"] = len(matched) - len(supported)
    if selected_dates:
        audit["first_selected_date"] = min(selected_dates)
        audit["last_selected_date"] = max(selected_dates)
    return experiment_rows, audit, date_support


def load_experiment_rows(
    *,
    data_root: str | Path,
    family: str,
    cutoff_local: str = DEFAULT_CUTOFF_LOCAL,
    specs: Sequence[MarketSpec] = BUILTIN_SPECS,
) -> dict[str, Any]:
    """Load all built-in markets and preserve complete market/date support."""

    family = _canonical_family(family)
    rows: list[dict[str, Any]] = []
    market_support = []
    market_dates = []
    for spec in specs:
        market_rows, audit, date_support = load_market_rows(
            data_root=data_root,
            spec=spec,
            family=family,
            cutoff_local=cutoff_local,
        )
        rows.extend(market_rows)
        market_support.append(audit)
        market_dates.extend(date_support)

    by_date: dict[str, dict[str, Any]] = {}
    for row in market_dates:
        item = by_date.setdefault(row["target_date"], {
            "target_date": row["target_date"],
            "selected_markets": 0,
            "settlement_matched_markets": 0,
            "family_supported_markets": 0,
            "missing_markets": [],
        })
        item["selected_markets"] += 1
        item["settlement_matched_markets"] += int(row["settlement_available"])
        item["family_supported_markets"] += int(
            row["settlement_available"] and row["family_supported"]
        )
        if row["settlement_available"] and not row["family_supported"]:
            item["missing_markets"].append(row["market_id"])
    for item in by_date.values():
        item["missing_markets"].sort()

    return {
        "rows": sorted(rows, key=lambda row: (row["target_date"], row["market_id"])),
        "support": {
            "market_count_requested": len(specs),
            "market_count_with_baseline_settlement": len({row["market_id"] for row in rows}),
            "market_count_with_family_support": len({
                row["market_id"] for row in rows if row["family_supported"]
            }),
            "matched_market_dates": len(rows),
            "family_supported_market_dates": sum(row["family_supported"] for row in rows),
            "family_missing_market_dates": sum(not row["family_supported"] for row in rows),
            "fleet_dates": len({row["target_date"] for row in rows}),
            "family_supported_fleet_dates": len({
                row["target_date"] for row in rows if row["family_supported"]
            }),
            "by_market": market_support,
            "by_date": [by_date[key] for key in sorted(by_date)],
            "by_market_date": market_dates,
        },
    }


def chronological_plan(
    dates: Iterable[str],
    *,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    folds: int = DEFAULT_FOLDS,
    min_train_dates: int = 30,
    min_holdout_dates: int = 14,
) -> dict[str, Any]:
    """Predeclare an expanding-window development plan and terminal holdout."""

    unique_dates = sorted(set(dates))
    if not 0.0 < float(holdout_fraction) < 1.0:
        raise ValueError("holdout_fraction must be between zero and one")
    if folds < 1:
        raise ValueError("folds must be positive")
    holdout_count = max(min_holdout_dates, int(math.ceil(len(unique_dates) * holdout_fraction)))
    if holdout_count >= len(unique_dates):
        return {
            "status": "BLOCKED_INSUFFICIENT_DATES",
            "all_dates": unique_dates,
            "development_dates": [],
            "holdout_dates": unique_dates,
            "holdout_start": unique_dates[0] if unique_dates else None,
            "folds": [],
        }
    development = unique_dates[:-holdout_count]
    holdout = unique_dates[-holdout_count:]
    if len(development) <= min_train_dates:
        return {
            "status": "BLOCKED_INSUFFICIENT_DATES",
            "all_dates": unique_dates,
            "development_dates": development,
            "holdout_dates": holdout,
            "holdout_start": holdout[0],
            "folds": [],
        }
    validation_pool = development[min_train_dates:]
    actual_folds = min(folds, len(validation_pool))
    base, extra = divmod(len(validation_pool), actual_folds)
    fold_rows = []
    cursor = min_train_dates
    for index in range(actual_folds):
        size = base + int(index < extra)
        validation_dates = development[cursor:cursor + size]
        train_dates = development[:cursor]
        cursor += size
        fold_rows.append({
            "fold": index + 1,
            "train_dates": train_dates,
            "validation_dates": validation_dates,
            "train_start": train_dates[0],
            "train_end": train_dates[-1],
            "validation_start": validation_dates[0],
            "validation_end": validation_dates[-1],
        })
    return {
        "status": "READY",
        "all_dates": unique_dates,
        "development_dates": development,
        "holdout_dates": holdout,
        "holdout_start": holdout[0],
        "folds": fold_rows,
    }


def _supported_rows_for_dates(
    rows: Sequence[Mapping[str, Any]], dates: Iterable[str]
) -> list[dict[str, Any]]:
    date_set = set(dates)
    return [dict(row) for row in rows if row.get("family_supported") and row.get("target_date") in date_set]


def _matrix(rows: Sequence[Mapping[str, Any]], family: str) -> np.ndarray:
    columns = FEATURES_BY_FAMILY[_canonical_family(family)]
    return np.asarray(
        [[float((row.get("features") or {})[column]) for column in columns] for row in rows],
        dtype=float,
    )


def fit_family_residual_model(
    rows: Sequence[Mapping[str, Any]], family: str, *, ridge_alpha: float = DEFAULT_RIDGE_ALPHA
):
    """Fit a family-only residual adjustment with no free bias correction."""

    if not rows:
        raise ValueError("cannot fit residual model without rows")
    target = np.asarray([float(row["baseline_residual_c"]) for row in rows], dtype=float)
    model = make_pipeline(
        StandardScaler(),
        Ridge(alpha=float(ridge_alpha), fit_intercept=False),
    )
    model.fit(_matrix(rows, family), target)
    return model


def predict_rows(
    model,
    rows: Sequence[Mapping[str, Any]],
    family: str,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    corrections = model.predict(_matrix(rows, family))
    output = []
    for row, correction in zip(rows, corrections):
        item = dict(row)
        item["predicted_family_residual_c"] = float(correction)
        item["variant_forecast_high_c"] = float(row["baseline_forecast_high_c"]) + float(correction)
        output.append(item)
    return output


def _percentile(sorted_values: Sequence[float], quantile: float) -> float | None:
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * float(quantile)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    fraction = position - lower
    return float(sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction)


def _error_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, float | int | None]:
    if not rows:
        return {
            "market_dates": 0,
            "baseline_mae_c": None,
            "variant_mae_c": None,
            "mae_delta_c": None,
            "baseline_rmse_c": None,
            "variant_rmse_c": None,
            "rmse_delta_c": None,
        }
    baseline_errors = [
        float(row["baseline_forecast_high_c"]) - float(row["settlement_high_c"])
        for row in rows
    ]
    variant_errors = [
        float(row["variant_forecast_high_c"]) - float(row["settlement_high_c"])
        for row in rows
    ]
    baseline_mae = sum(abs(value) for value in baseline_errors) / len(rows)
    variant_mae = sum(abs(value) for value in variant_errors) / len(rows)
    baseline_rmse = math.sqrt(sum(value * value for value in baseline_errors) / len(rows))
    variant_rmse = math.sqrt(sum(value * value for value in variant_errors) / len(rows))
    return {
        "market_dates": len(rows),
        "baseline_mae_c": baseline_mae,
        "variant_mae_c": variant_mae,
        "mae_delta_c": variant_mae - baseline_mae,
        "baseline_rmse_c": baseline_rmse,
        "variant_rmse_c": variant_rmse,
        "rmse_delta_c": variant_rmse - baseline_rmse,
    }


def _sign_counts(values: Iterable[float], *, tolerance: float = 1e-12) -> dict[str, Any]:
    values = [float(value) for value in values]
    improvements = sum(value < -tolerance for value in values)
    regressions = sum(value > tolerance for value in values)
    ties = len(values) - improvements - regressions
    non_ties = improvements + regressions
    if non_ties:
        tail = min(improvements, regressions)
        log_terms = [
            math.lgamma(non_ties + 1)
            - math.lgamma(k + 1)
            - math.lgamma(non_ties - k + 1)
            - non_ties * math.log(2.0)
            for k in range(tail + 1)
        ]
        max_log = max(log_terms)
        one_sided = math.exp(max_log) * sum(
            math.exp(value - max_log) for value in log_terms
        )
        p_value = min(1.0, 2.0 * one_sided)
    else:
        p_value = 1.0
    return {
        "improvements": improvements,
        "regressions": regressions,
        "ties": ties,
        "non_ties": non_ties,
        "two_sided_sign_test_p": p_value,
    }


def _fleet_date_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["target_date"])].append(row)
    output = []
    for target_date, date_rows in sorted(grouped.items()):
        metrics = _error_metrics(date_rows)
        output.append({
            "target_date": target_date,
            "market_dates": len(date_rows),
            "baseline_mae_c": metrics["baseline_mae_c"],
            "variant_mae_c": metrics["variant_mae_c"],
            "mae_delta_c": metrics["mae_delta_c"],
            "baseline_rmse_c": metrics["baseline_rmse_c"],
            "variant_rmse_c": metrics["variant_rmse_c"],
            "rmse_delta_c": metrics["rmse_delta_c"],
        })
    return output


def _distribution(values: Iterable[float]) -> dict[str, float | int | None]:
    values = sorted(float(value) for value in values)
    if not values:
        return {
            "n": 0,
            "min": None,
            "p05": None,
            "median": None,
            "p95": None,
            "max": None,
            "mean": None,
            "std": None,
        }
    mean = sum(values) / len(values)
    return {
        "n": len(values),
        "min": values[0],
        "p05": _percentile(values, 0.05),
        "median": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "max": values[-1],
        "mean": mean,
        "std": math.sqrt(sum((value - mean) ** 2 for value in values) / len(values)),
    }


def paired_cluster_bootstrap(
    rows: Sequence[Mapping[str, Any]],
    *,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
    replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    """Resample whole fleet target dates and recompute paired MAE/RMSE deltas."""

    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["target_date"])].append(row)
    dates = sorted(grouped)
    empty = {
        "cluster_unit": "fleet_target_date",
        "clusters": len(dates),
        "replicates": int(replicates),
        "seed": int(seed),
        "mae_delta_c_95ci": {"low": None, "high": None},
        "rmse_delta_c_95ci": {"low": None, "high": None},
    }
    if not dates or replicates <= 0:
        return empty
    rng = random.Random(int(seed))
    mae_deltas = []
    rmse_deltas = []
    for _ in range(int(replicates)):
        sampled: list[Mapping[str, Any]] = []
        for _ in dates:
            sampled.extend(grouped[dates[rng.randrange(len(dates))]])
        metrics = _error_metrics(sampled)
        mae_deltas.append(float(metrics["mae_delta_c"]))
        rmse_deltas.append(float(metrics["rmse_delta_c"]))
    mae_deltas.sort()
    rmse_deltas.sort()
    return {
        **empty,
        "mae_delta_c_95ci": {
            "low": _percentile(mae_deltas, 0.025),
            "high": _percentile(mae_deltas, 0.975),
        },
        "rmse_delta_c_95ci": {
            "low": _percentile(rmse_deltas, 0.025),
            "high": _percentile(rmse_deltas, 0.975),
        },
    }


def paired_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    metrics = _error_metrics(rows)
    fleet_dates = _fleet_date_rows(rows)
    row_abs_deltas = [
        abs(float(row["variant_forecast_high_c"]) - float(row["settlement_high_c"]))
        - abs(float(row["baseline_forecast_high_c"]) - float(row["settlement_high_c"]))
        for row in rows
    ]
    by_market = []
    for market_id in sorted({str(row.get("market_id") or "") for row in rows}):
        market_rows = [row for row in rows if str(row.get("market_id") or "") == market_id]
        market_metrics = _error_metrics(market_rows)
        market_deltas = [
            abs(float(row["variant_forecast_high_c"]) - float(row["settlement_high_c"]))
            - abs(float(row["baseline_forecast_high_c"]) - float(row["settlement_high_c"]))
            for row in market_rows
        ]
        by_market.append({
            "market_id": market_id,
            **market_metrics,
            "sign_counts": _sign_counts(market_deltas),
        })
    by_year = []
    for year in sorted({str(row["target_date"])[:4] for row in rows}):
        year_rows = [row for row in rows if str(row["target_date"]).startswith(year)]
        by_year.append({"year": int(year), **_error_metrics(year_rows)})
    return {
        **metrics,
        "fleet_dates": len(fleet_dates),
        "market_date_sign_counts": _sign_counts(row_abs_deltas),
        "fleet_date_sign_counts": _sign_counts(row["mae_delta_c"] for row in fleet_dates),
        "fleet_date_cluster_bootstrap": paired_cluster_bootstrap(
            rows, seed=bootstrap_seed, replicates=bootstrap_replicates
        ),
        "by_market": by_market,
        "by_year": by_year,
        "predicted_family_residual_distribution_c": _distribution(
            row["predicted_family_residual_c"]
            for row in rows
            if row.get("predicted_family_residual_c") is not None
        ),
        "paired_fleet_date_errors": fleet_dates,
    }


def residual_model_diagnostics(model, family: str) -> dict[str, Any]:
    scaler = model.named_steps["standardscaler"]
    ridge = model.named_steps["ridge"]
    return {
        "fit_intercept": bool(ridge.fit_intercept),
        "ridge_alpha": float(ridge.alpha),
        "standardized_coefficients": [
            {
                "feature": feature,
                "coefficient_c": float(coefficient),
                "train_mean": float(mean),
                "train_scale": float(scale),
            }
            for feature, coefficient, mean, scale in zip(
                FEATURES_BY_FAMILY[_canonical_family(family)],
                np.ravel(ridge.coef_),
                np.ravel(scaler.mean_),
                np.ravel(scaler.scale_),
            )
        ],
    }


def _support_blockers(
    rows: Sequence[Mapping[str, Any]], plan: Mapping[str, Any], thresholds: Thresholds
) -> list[str]:
    supported = [row for row in rows if row.get("family_supported")]
    blockers = []
    if not supported:
        return [
            "zero market-dates have the selected family on an explicit issue-time row before the cutoff"
        ]
    markets = {row["market_id"] for row in supported}
    if len(markets) < thresholds.min_markets:
        blockers.append(
            f"family support covers {len(markets)} markets; minimum is {thresholds.min_markets}"
        )
    if plan.get("status") != "READY":
        blockers.append("not enough chronological dates to reserve development and holdout ranges")
        return blockers
    holdout_rows = _supported_rows_for_dates(rows, plan["holdout_dates"])
    holdout_dates = {row["target_date"] for row in holdout_rows}
    if len(holdout_rows) < thresholds.min_holdout_rows:
        blockers.append(
            f"holdout has {len(holdout_rows)} supported market-dates; minimum is {thresholds.min_holdout_rows}"
        )
    if len(holdout_dates) < thresholds.min_holdout_dates:
        blockers.append(
            f"holdout has {len(holdout_dates)} supported fleet dates; minimum is {thresholds.min_holdout_dates}"
        )
    for fold in plan.get("folds") or []:
        train_rows = _supported_rows_for_dates(rows, fold["train_dates"])
        validation_rows = _supported_rows_for_dates(rows, fold["validation_dates"])
        train_dates = {row["target_date"] for row in train_rows}
        validation_dates = {row["target_date"] for row in validation_rows}
        if len(train_rows) < thresholds.min_train_rows or len(train_dates) < thresholds.min_train_dates:
            blockers.append(
                f"fold {fold['fold']} training support is {len(train_rows)} rows/{len(train_dates)} dates"
            )
        if (
            len(validation_rows) < thresholds.min_validation_rows
            or len(validation_dates) < thresholds.min_validation_dates
        ):
            blockers.append(
                f"fold {fold['fold']} validation support is {len(validation_rows)} rows/"
                f"{len(validation_dates)} dates"
            )
    return blockers


def evaluate_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    family: str,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    folds: int = DEFAULT_FOLDS,
    ridge_alpha: float = DEFAULT_RIDGE_ALPHA,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    thresholds: Thresholds = Thresholds(),
) -> dict[str, Any]:
    """Evaluate baseline and one family on identical, time-safe partitions."""

    family = _canonical_family(family)
    # Provider coverage is an exogenous availability constraint.  Define the
    # experiment corpus from supported dates before looking at any outcome, then
    # score baseline and family arms on exactly those same rows.
    plan = chronological_plan(
        (row["target_date"] for row in rows if row.get("family_supported")),
        holdout_fraction=holdout_fraction,
        folds=folds,
        min_train_dates=thresholds.min_train_dates,
        min_holdout_dates=thresholds.min_holdout_dates,
    )
    blockers = _support_blockers(rows, plan, thresholds)
    base_payload = {
        "status": "BLOCKED" if blockers else "RESEARCH_ONLY_EVALUATED",
        "blockers": blockers,
        "temporal_plan": {
            "status": plan.get("status"),
            "all_date_count": len(plan.get("all_dates") or []),
            "development_date_count": len(plan.get("development_dates") or []),
            "holdout_date_count": len(plan.get("holdout_dates") or []),
            "development_start": (plan.get("development_dates") or [None])[0],
            "development_end": (plan.get("development_dates") or [None])[-1],
            "holdout_start": plan.get("holdout_start"),
            "holdout_end": (plan.get("holdout_dates") or [None])[-1],
            "folds": [
                {
                    key: value
                    for key, value in fold.items()
                    if key not in {"train_dates", "validation_dates"}
                }
                for fold in plan.get("folds") or []
            ],
        },
        "cross_validation": None,
        "holdout": None,
        "signal_assessment": "not_evaluated",
    }
    if blockers:
        return base_payload

    cv_predictions = []
    fold_summaries = []
    for fold in plan["folds"]:
        train_rows = _supported_rows_for_dates(rows, fold["train_dates"])
        validation_rows = _supported_rows_for_dates(rows, fold["validation_dates"])
        model = fit_family_residual_model(train_rows, family, ridge_alpha=ridge_alpha)
        predictions = predict_rows(model, validation_rows, family)
        cv_predictions.extend(predictions)
        summary = paired_summary(
            predictions,
            bootstrap_seed=bootstrap_seed + fold["fold"],
            bootstrap_replicates=bootstrap_replicates,
        )
        fold_summaries.append({
            "fold": fold["fold"],
            "train_start": fold["train_start"],
            "train_end": fold["train_end"],
            "validation_start": fold["validation_start"],
            "validation_end": fold["validation_end"],
            "train_market_dates": len(train_rows),
            "validation_market_dates": len(validation_rows),
            "model": residual_model_diagnostics(model, family),
            "metrics": summary,
        })

    development_rows = _supported_rows_for_dates(rows, plan["development_dates"])
    holdout_rows = _supported_rows_for_dates(rows, plan["holdout_dates"])
    final_model = fit_family_residual_model(development_rows, family, ridge_alpha=ridge_alpha)
    holdout_predictions = predict_rows(final_model, holdout_rows, family)
    cv_summary = paired_summary(
        cv_predictions,
        bootstrap_seed=bootstrap_seed + 10_000,
        bootstrap_replicates=bootstrap_replicates,
    )
    holdout_summary = paired_summary(
        holdout_predictions,
        bootstrap_seed=bootstrap_seed,
        bootstrap_replicates=bootstrap_replicates,
    )
    mae_ci = holdout_summary["fleet_date_cluster_bootstrap"]["mae_delta_c_95ci"]
    if (
        holdout_summary["mae_delta_c"] is not None
        and holdout_summary["mae_delta_c"] < 0
        and mae_ci["high"] is not None
        and mae_ci["high"] < 0
    ):
        assessment = "holdout_improvement_with_cluster_ci_below_zero"
    elif holdout_summary["mae_delta_c"] is not None and holdout_summary["mae_delta_c"] > 0:
        assessment = "holdout_regression"
    else:
        assessment = "holdout_inconclusive"
    return {
        **base_payload,
        "cross_validation": {
            "aggregate": cv_summary,
            "folds": fold_summaries,
        },
        "holdout": {
            "train_market_dates": len(development_rows),
            "train_fleet_dates": len({row["target_date"] for row in development_rows}),
            "model": residual_model_diagnostics(final_model, family),
            "metrics": holdout_summary,
        },
        "signal_assessment": assessment,
    }


def build_payload(
    *,
    data_root: str | Path,
    family: str,
    cutoff_local: str = DEFAULT_CUTOFF_LOCAL,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    folds: int = DEFAULT_FOLDS,
    ridge_alpha: float = DEFAULT_RIDGE_ALPHA,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    thresholds: Thresholds = Thresholds(),
    specs: Sequence[MarketSpec] = BUILTIN_SPECS,
) -> dict[str, Any]:
    family = _canonical_family(family)
    loaded = load_experiment_rows(
        data_root=data_root,
        family=family,
        cutoff_local=cutoff_local,
        specs=specs,
    )
    evaluation = evaluate_rows(
        loaded["rows"],
        family=family,
        holdout_fraction=holdout_fraction,
        folds=folds,
        ridge_alpha=ridge_alpha,
        bootstrap_replicates=bootstrap_replicates,
        bootstrap_seed=bootstrap_seed,
        thresholds=thresholds,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "research_only": True,
        "experiment": {
            "family": family,
            "feature_columns": list(FEATURES_BY_FAMILY[family]),
            "raw_family_columns": list(RAW_FIELDS_BY_FAMILY[family]),
            "data_root": str(Path(data_root)),
            "market_ids": [spec.id for spec in specs],
            "cutoff_local": cutoff_local,
            "cutoff_rule": "issue_time < target_date local cutoff (strict)",
            "forbidden_issue_time_bases": sorted(FORBIDDEN_ISSUE_TIME_BASES),
            "target_unit": "C",
            "target": "WU daily settlement high minus forecast_high, both converted to Celsius",
            "baseline_arm": "forecast_high from the latest admissible explicit issue",
            "variant_arm": "baseline plus Ridge family-only residual; standardized train-only; no intercept",
            "ridge_alpha": float(ridge_alpha),
            "holdout_fraction": float(holdout_fraction),
            "blocked_chronological_folds": int(folds),
            "temporal_corpus_rule": "fleet dates with family support, selected without outcome data",
            "bootstrap_cluster": "fleet_target_date",
            "bootstrap_replicates": int(bootstrap_replicates),
            "bootstrap_seed": int(bootstrap_seed),
            "thresholds": thresholds.__dict__,
        },
        "support": loaded["support"],
        "evaluation": evaluation,
        "guardrails": {
            "continuous_archive_used_for_performance": False,
            "network_used": False,
            "mirror_mutated": False,
            "one_family_only": family,
            "holdout_opened": evaluation["status"] == "RESEARCH_ONLY_EVALUATED",
            "production_change_authorized": False,
        },
    }


def write_markdown_report(path: str | Path, payload: Mapping[str, Any]) -> Path:
    path = Path(path)
    experiment = payload["experiment"]
    support = payload["support"]
    evaluation = payload["evaluation"]
    lines = [
        f"# Offline Tmax Predictor Evaluation: {experiment['family']}",
        "",
        f"Generated: {payload['generated_at_utc']}",
        f"Status: `{evaluation['status']}`",
        f"Signal assessment: `{evaluation['signal_assessment']}`",
        "",
        "This is a research-only, one-family experiment. Negative deltas favor the family arm.",
        "The stitched continuous archive is counted for support diagnostics but never admitted to scoring.",
        "",
        "## Leakage and Evaluation Contract",
        "",
    ]
    lines += markdown_table(
        ["Control", "Predeclared value"],
        [
            ["Family", experiment["family"]],
            ["Issue cutoff", f"strictly before {experiment['cutoff_local']} local on target date"],
            ["Forbidden basis", ", ".join(experiment["forbidden_issue_time_bases"])],
            ["Target unit", "Celsius (including physical conversion of Fahrenheit markets)"],
            ["Folds", experiment["blocked_chronological_folds"]],
            ["Temporal corpus", experiment["temporal_corpus_rule"]],
            ["Untouched holdout", f"terminal {experiment['holdout_fraction']:.0%} of fleet dates"],
            ["Bootstrap", f"{experiment['bootstrap_replicates']} fleet-date clusters; seed {experiment['bootstrap_seed']}"],
        ],
    )
    lines += ["", "## Result", ""]
    if evaluation["blockers"]:
        lines.append("Holdout scoring was not opened:")
        lines.append("")
        lines.extend(f"- {reason}" for reason in evaluation["blockers"])
    else:
        cv = evaluation["cross_validation"]["aggregate"]
        holdout = evaluation["holdout"]["metrics"]
        ci = holdout["fleet_date_cluster_bootstrap"]
        lines += markdown_table(
            [
                "Split",
                "Market-dates",
                "Fleet dates",
                "Baseline MAE C",
                "Variant MAE C",
                "MAE delta C",
                "MAE delta 95% CI",
                "RMSE delta C",
                "RMSE delta 95% CI",
                "Fleet-date +/-/=",
            ],
            [
                [
                    "blocked CV",
                    cv["market_dates"],
                    cv["fleet_dates"],
                    fmt_num(cv["baseline_mae_c"]),
                    fmt_num(cv["variant_mae_c"]),
                    fmt_signed(cv["mae_delta_c"]),
                    f"[{fmt_signed(cv['fleet_date_cluster_bootstrap']['mae_delta_c_95ci']['low'])}, {fmt_signed(cv['fleet_date_cluster_bootstrap']['mae_delta_c_95ci']['high'])}]",
                    fmt_signed(cv["rmse_delta_c"]),
                    f"[{fmt_signed(cv['fleet_date_cluster_bootstrap']['rmse_delta_c_95ci']['low'])}, {fmt_signed(cv['fleet_date_cluster_bootstrap']['rmse_delta_c_95ci']['high'])}]",
                    f"{cv['fleet_date_sign_counts']['improvements']}/{cv['fleet_date_sign_counts']['regressions']}/{cv['fleet_date_sign_counts']['ties']}",
                ],
                [
                    "untouched holdout",
                    holdout["market_dates"],
                    holdout["fleet_dates"],
                    fmt_num(holdout["baseline_mae_c"]),
                    fmt_num(holdout["variant_mae_c"]),
                    fmt_signed(holdout["mae_delta_c"]),
                    f"[{fmt_signed(ci['mae_delta_c_95ci']['low'])}, {fmt_signed(ci['mae_delta_c_95ci']['high'])}]",
                    fmt_signed(holdout["rmse_delta_c"]),
                    f"[{fmt_signed(ci['rmse_delta_c_95ci']['low'])}, {fmt_signed(ci['rmse_delta_c_95ci']['high'])}]",
                    f"{holdout['fleet_date_sign_counts']['improvements']}/{holdout['fleet_date_sign_counts']['regressions']}/{holdout['fleet_date_sign_counts']['ties']}",
                ],
            ],
        )
        lines += ["", "## Untouched Holdout by Market", ""]
        lines += markdown_table(
            ["Market", "Rows", "Baseline MAE C", "Variant MAE C", "MAE delta C", "RMSE delta C", "+/-/="],
            [
                [
                    row["market_id"],
                    row["market_dates"],
                    fmt_num(row["baseline_mae_c"]),
                    fmt_num(row["variant_mae_c"]),
                    fmt_signed(row["mae_delta_c"]),
                    fmt_signed(row["rmse_delta_c"]),
                    f"{row['sign_counts']['improvements']}/{row['sign_counts']['regressions']}/{row['sign_counts']['ties']}",
                ]
                for row in holdout["by_market"]
            ],
        )
    lines += ["", "## Support by Market", ""]
    lines += markdown_table(
        [
            "Market",
            "Forecast rows",
            "Explicit-time rows",
            "Admissible rows",
            "Matched dates",
            "Family dates",
            "Forbidden rich rows",
            "Forecast mtime UTC",
        ],
        [
            [
                row["market_id"],
                row["forecast_rows"],
                row["rows_with_explicit_issue_time"],
                row["admissible_rows"],
                row["matched_settlement_dates"],
                row["family_supported_dates"],
                row["forbidden_stitched_family_rows"],
                row["provenance"]["forecast_history"]["mtime_utc"] or "-",
            ]
            for row in support["by_market"]
        ],
    )
    lines += ["", "## Interpretation", ""]
    if evaluation["status"] == "BLOCKED":
        lines.append(
            "A family with no admissible support needs a new issue-time-preserving historical capture/backfill before it can be tested. "
            "The populated stitched fields cannot be substituted because doing so would leak future forecast revisions into the target date."
        )
    elif evaluation["signal_assessment"] == "holdout_improvement_with_cluster_ci_below_zero":
        lines.append(
            "The family improves the primary holdout MAE with the fleet-date clustered interval below zero. "
            "This remains a research result that needs release-bound replay evidence before any serving proposal."
        )
    elif evaluation["signal_assessment"] == "holdout_regression":
        lines.append("The untouched holdout regresses; stop this feature-family line unless new evidence changes the data contract.")
    else:
        lines.append(
            "Point estimates favor the family, but the primary holdout MAE fleet-date interval includes zero. "
            "Treat the result as promising but inconclusive; do not promote or add a production collector from this evidence alone."
        )
    lines += ["", "No serving, collector, promotion, or live-trading change follows from this report."]
    return write_text_atomic(path, "\n".join(lines) + "\n")


def run(args: argparse.Namespace) -> dict[str, Any]:
    data_root, output_paths = resolve_paths_outside_read_only_root(
        read_only_root=args.data_root,
        paths={"out": args.out, "report": args.report},
    )
    thresholds = Thresholds(
        min_markets=args.min_markets,
        min_train_dates=args.min_train_dates,
        min_validation_dates=args.min_validation_dates,
        min_holdout_dates=args.min_holdout_dates,
        min_train_rows=args.min_train_rows,
        min_validation_rows=args.min_validation_rows,
        min_holdout_rows=args.min_holdout_rows,
    )
    payload = build_payload(
        data_root=data_root,
        family=args.family,
        cutoff_local=args.cutoff_local,
        holdout_fraction=args.holdout_fraction,
        folds=args.folds,
        ridge_alpha=args.ridge_alpha,
        bootstrap_replicates=args.bootstrap_replicates,
        bootstrap_seed=args.bootstrap_seed,
        thresholds=thresholds,
    )
    out = output_paths["out"]
    write_json_atomic(out, payload)
    write_markdown_report(output_paths["report"], payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate exactly one new Tmax predictor family with point-in-time-safe forecast rows."
    )
    parser.add_argument("--data-root", required=True, help="Read-only mirrored data root.")
    parser.add_argument("--family", required=True, choices=sorted(FAMILY_ALIASES))
    parser.add_argument("--cutoff-local", default=DEFAULT_CUTOFF_LOCAL)
    parser.add_argument("--holdout-fraction", type=float, default=DEFAULT_HOLDOUT_FRACTION)
    parser.add_argument("--folds", type=int, default=DEFAULT_FOLDS)
    parser.add_argument("--ridge-alpha", type=float, default=DEFAULT_RIDGE_ALPHA)
    parser.add_argument("--bootstrap-replicates", type=int, default=DEFAULT_BOOTSTRAP_REPLICATES)
    parser.add_argument("--bootstrap-seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    parser.add_argument("--min-markets", type=int, default=Thresholds.min_markets)
    parser.add_argument("--min-train-dates", type=int, default=Thresholds.min_train_dates)
    parser.add_argument("--min-validation-dates", type=int, default=Thresholds.min_validation_dates)
    parser.add_argument("--min-holdout-dates", type=int, default=Thresholds.min_holdout_dates)
    parser.add_argument("--min-train-rows", type=int, default=Thresholds.min_train_rows)
    parser.add_argument("--min-validation-rows", type=int, default=Thresholds.min_validation_rows)
    parser.add_argument("--min-holdout-rows", type=int, default=Thresholds.min_holdout_rows)
    parser.add_argument("--out", required=True, help="Scratch JSON output path.")
    parser.add_argument("--report", required=True, help="Scratch Markdown output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    payload = run(build_parser().parse_args(argv))
    evaluation = payload["evaluation"]
    print(
        f"Offline Tmax {payload['experiment']['family']}: {evaluation['status']} "
        f"({payload['support']['family_supported_market_dates']} supported market-dates)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
