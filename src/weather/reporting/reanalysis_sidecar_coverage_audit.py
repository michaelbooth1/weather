"""Audit reanalysis sidecar feature-group coverage for replay windows."""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from weather.io import write_json_atomic
from weather.paths import data_path
from weather.reporting.formatting import fmt_pct, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("reanalysis_sidecar_coverage_audit")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_REANALYSIS_ROOT = data_path() / "reanalysis"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "reanalysis_sidecar_coverage_audit.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "reanalysis_sidecar_coverage_audit_report.md"


@dataclass(frozen=True)
class FeatureGroup:
    name: str
    label: str
    columns: tuple[str, ...]
    availability_column: str | None = None
    availability_value: float | None = None


FEATURE_GROUPS = (
    FeatureGroup(
        "base_sidecar",
        "Base sidecar",
        ("reanalysis_synoptic_available",),
        availability_column="reanalysis_synoptic_available",
        availability_value=1.0,
    ),
    FeatureGroup(
        "core_antecedent",
        "Core antecedent weather",
        (
            "reanalysis_prev_day_max_temp",
            "reanalysis_prev_day_min_temp",
            "reanalysis_prev_day_avg_temp",
            "reanalysis_prev_day_temp_range",
            "reanalysis_prev_day_max_dewpoint",
            "reanalysis_prev_day_max_wind_kmh",
            "reanalysis_prev_day_max_gust_kmh",
            "reanalysis_prev_day_pressure_mean_hpa",
            "reanalysis_pressure_change_24h_hpa",
            "reanalysis_prev_day_heat_anomaly",
            "reanalysis_prev_3d_heat_anomaly",
            "reanalysis_prev_7d_heat_anomaly",
        ),
    ),
    FeatureGroup(
        "rich_surface",
        "Rich Open-Meteo archive fields",
        (
            "reanalysis_prev_day_soil_temperature_0_to_7cm_mean",
            "reanalysis_prev_day_soil_moisture_0_to_7cm_mean",
            "reanalysis_prev_day_vapour_pressure_deficit_mean",
            "reanalysis_prev_day_et0_fao_evapotranspiration_sum",
            "reanalysis_prev_day_shortwave_radiation_sum",
            "reanalysis_prev_day_low_cloud_mean",
            "reanalysis_prev_day_mid_cloud_mean",
            "reanalysis_prev_day_high_cloud_mean",
        ),
    ),
    FeatureGroup(
        "pressure_level",
        "NOAA PSL pressure-level fields",
        (
            "reanalysis_prev_day_temperature_850hpa_c",
            "reanalysis_prev_day_geopotential_height_500hpa_m",
            "reanalysis_prev_day_thickness_1000_500hpa_m",
        ),
        availability_column="reanalysis_pressure_level_available",
        availability_value=1.0,
    ),
    FeatureGroup(
        "teleconnection",
        "Lagged ENSO/PNA fields",
        (
            "reanalysis_teleconnection_available",
            "reanalysis_enso_oni_lagged",
            "reanalysis_enso_oni_lag_months",
            "reanalysis_enso_el_nino_flag",
            "reanalysis_enso_la_nina_flag",
            "reanalysis_pna_lagged",
            "reanalysis_pna_lag_months",
            "reanalysis_pna_positive_flag",
            "reanalysis_pna_negative_flag",
        ),
        availability_column="reanalysis_teleconnection_available",
        availability_value=1.0,
    ),
    FeatureGroup(
        "static_context",
        "Static coastal and city-context fields",
        (
            "reanalysis_coastal_flag",
            "reanalysis_continentality_km",
            "reanalysis_sea_breeze_context_flag",
            "reanalysis_lake_breeze_context_flag",
            "reanalysis_marine_context_station_count",
        ),
    ),
)
FEATURE_GROUPS_BY_NAME = {group.name: group for group in FEATURE_GROUPS}
DEFAULT_REQUIRED_GROUPS = ("rich_surface", "pressure_level")
BLANK_VALUES = {"", "na", "nan", "none", "null", "n/a"}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in BLANK_VALUES:
        return None
    try:
        result = float(text)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def is_present(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if text.lower() in BLANK_VALUES:
        return False
    if text.lower() in {"true", "false"}:
        return True
    numeric = safe_float(text)
    if numeric is not None:
        return True
    return bool(text)


def read_csv_rows(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def local_date(row: dict[str, Any]) -> date | None:
    return parse_date(row.get("local_date"))


def filter_rows_by_date(
    rows: list[dict[str, Any]],
    start: date | None,
    end: date | None,
) -> list[dict[str, Any]]:
    if start is None and end is None:
        return list(rows)
    out = []
    for row in rows:
        day = local_date(row)
        if day is None:
            continue
        if start is not None and day < start:
            continue
        if end is not None and day > end:
            continue
        out.append(row)
    return out


def row_has_group(row: dict[str, Any], group: FeatureGroup) -> bool:
    if group.availability_column:
        availability = safe_float(row.get(group.availability_column))
        if group.availability_value is not None and availability != group.availability_value:
            return False
        if group.availability_value is None and not is_present(row.get(group.availability_column)):
            return False
    return all(is_present(row.get(column)) for column in group.columns)


def group_coverage(rows: list[dict[str, Any]], group: FeatureGroup) -> dict[str, Any]:
    row_count = len(rows)
    present_by_column = {
        column: sum(1 for row in rows if is_present(row.get(column)))
        for column in group.columns
    }
    if group.availability_column and group.availability_column not in present_by_column:
        present_by_column[group.availability_column] = sum(
            1 for row in rows
            if safe_float(row.get(group.availability_column)) == group.availability_value
        )
    complete_dates = [
        local_date(row)
        for row in rows
        if row_has_group(row, group) and local_date(row) is not None
    ]
    complete_rows = len(complete_dates)
    if row_count == 0:
        status = "MISSING_ROWS"
    elif complete_rows == row_count:
        status = "PASS"
    elif complete_rows > 0:
        status = "PARTIAL"
    else:
        status = "MISSING"
    return {
        "name": group.name,
        "label": group.label,
        "row_count": row_count,
        "complete_rows": complete_rows,
        "coverage": complete_rows / row_count if row_count else 0.0,
        "status": status,
        "first_complete_date": min(complete_dates).isoformat() if complete_dates else None,
        "last_complete_date": max(complete_dates).isoformat() if complete_dates else None,
        "present_by_column": present_by_column,
        "missing_columns": [
            column
            for column, count in present_by_column.items()
            if row_count > 0 and count == 0
        ],
        "partial_columns": [
            column
            for column, count in present_by_column.items()
            if row_count > 0 and 0 < count < row_count
        ],
    }


def sidecar_paths(reanalysis_root: str | Path) -> list[Path]:
    root = Path(reanalysis_root)
    return sorted(root.glob("*/features/reanalysis_synoptic_features.csv"))


def market_from_path(path: Path, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        market_id = str(row.get("market_id") or "").strip()
        if market_id:
            return market_id
    try:
        return path.parent.parent.name
    except IndexError:
        return path.stem


def date_bounds(rows: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    dates = [day for row in rows if (day := local_date(row)) is not None]
    if not dates:
        return None, None
    return min(dates).isoformat(), max(dates).isoformat()


def audit_sidecar(
    path: str | Path,
    *,
    target_start: date | None = None,
    target_end: date | None = None,
    required_groups: tuple[str, ...] = DEFAULT_REQUIRED_GROUPS,
) -> dict[str, Any]:
    path = Path(path)
    rows = read_csv_rows(path)
    target_rows = filter_rows_by_date(rows, target_start, target_end)
    first_date, last_date = date_bounds(rows)
    groups_all = {
        group.name: group_coverage(rows, group)
        for group in FEATURE_GROUPS
    }
    groups_target = {
        group.name: group_coverage(target_rows, group)
        for group in FEATURE_GROUPS
    }
    blockers = []
    if target_start is not None or target_end is not None:
        if not target_rows:
            blockers.append("target_window_missing_rows")
        for group_name in required_groups:
            group_status = (groups_target.get(group_name) or {}).get("status")
            if group_status != "PASS":
                blockers.append(f"{group_name}:{group_status or 'UNKNOWN'}")
    status = "BLOCK" if blockers else "PASS"
    return {
        "market_id": market_from_path(path, rows),
        "path": str(path),
        "rows": len(rows),
        "target_rows": len(target_rows),
        "first_date": first_date,
        "last_date": last_date,
        "target_start": target_start.isoformat() if target_start else None,
        "target_end": target_end.isoformat() if target_end else None,
        "groups": groups_all,
        "target_window_groups": groups_target,
        "required_groups": list(required_groups),
        "status": status,
        "blockers": blockers,
    }


def normalize_required_groups(value: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if value is None:
        return DEFAULT_REQUIRED_GROUPS
    if isinstance(value, str):
        groups = [item.strip() for item in value.split(",") if item.strip()]
    else:
        groups = [str(item).strip() for item in value if str(item).strip()]
    unknown = sorted(set(groups) - set(FEATURE_GROUPS_BY_NAME))
    if unknown:
        raise ValueError(f"unknown feature group(s): {', '.join(unknown)}")
    return tuple(groups)


def build_payload(
    *,
    reanalysis_root: str | Path = DEFAULT_REANALYSIS_ROOT,
    target_start: str | date | None = None,
    target_end: str | date | None = None,
    required_groups: str | list[str] | tuple[str, ...] | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    start = parse_date(target_start)
    end = parse_date(target_end)
    required = normalize_required_groups(required_groups)
    sidecars = [
        audit_sidecar(
            path,
            target_start=start,
            target_end=end,
            required_groups=required,
        )
        for path in sidecar_paths(reanalysis_root)
    ]
    status_counts: dict[str, int] = {}
    required_group_counts = {
        group_name: {"PASS": 0, "PARTIAL": 0, "MISSING": 0, "MISSING_ROWS": 0}
        for group_name in required
    }
    for row in sidecars:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
        for group_name in required:
            group_status = (row.get("target_window_groups") or {}).get(group_name, {}).get("status")
            if group_status in required_group_counts[group_name]:
                required_group_counts[group_name][group_status] += 1
    blocking = [row for row in sidecars if row.get("status") == "BLOCK"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "reanalysis_root": str(Path(reanalysis_root)),
        "target_start": start.isoformat() if start else None,
        "target_end": end.isoformat() if end else None,
        "required_groups": list(required),
        "status": "BLOCK" if blocking else "PASS",
        "summary": {
            "markets": len(sidecars),
            "blocking_markets": len(blocking),
            "status_counts": status_counts,
            "required_group_target_status_counts": required_group_counts,
            "feature_groups": [
                {"name": group.name, "label": group.label, "columns": list(group.columns)}
                for group in FEATURE_GROUPS
            ],
        },
        "markets": sidecars,
    }


def fmt_coverage(group: dict[str, Any]) -> str:
    if not group:
        return "-"
    status = group.get("status") or "-"
    return f"{status} {fmt_pct(group.get('coverage'))}"


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Reanalysis Sidecar Coverage Audit",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: {payload.get('status')}",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Reanalysis root", payload.get("reanalysis_root")],
            ["Target start", payload.get("target_start")],
            ["Target end", payload.get("target_end")],
            ["Required target groups", ", ".join(payload.get("required_groups") or []) or "-"],
            ["Markets", summary.get("markets")],
            ["Blocking markets", summary.get("blocking_markets")],
        ],
    )
    lines += ["", "## Target Window Coverage", ""]
    lines += markdown_table(
        [
            "Market",
            "Rows",
            "Target rows",
            "Core",
            "Rich surface",
            "Pressure level",
            "Teleconnection",
            "Last rich",
            "Last pressure",
            "Status",
        ],
        [
            [
                row.get("market_id"),
                row.get("rows"),
                row.get("target_rows"),
                fmt_coverage((row.get("target_window_groups") or {}).get("core_antecedent")),
                fmt_coverage((row.get("target_window_groups") or {}).get("rich_surface")),
                fmt_coverage((row.get("target_window_groups") or {}).get("pressure_level")),
                fmt_coverage((row.get("target_window_groups") or {}).get("teleconnection")),
                ((row.get("groups") or {}).get("rich_surface") or {}).get("last_complete_date"),
                ((row.get("groups") or {}).get("pressure_level") or {}).get("last_complete_date"),
                row.get("status"),
            ]
            for row in sorted(payload.get("markets") or [], key=lambda item: str(item.get("market_id") or ""))
        ],
    )
    blocking = [row for row in payload.get("markets") or [] if row.get("status") == "BLOCK"]
    if blocking:
        lines += ["", "## Blocking Markets", ""]
        lines += markdown_table(
            ["Market", "Blockers", "Path"],
            [
                [
                    row.get("market_id"),
                    ", ".join(row.get("blockers") or []) or "-",
                    row.get("path"),
                ]
                for row in sorted(blocking, key=lambda item: str(item.get("market_id") or ""))
            ],
        )
    lines += ["", "## Feature Groups", ""]
    lines += markdown_table(
        ["Group", "Label", "Columns"],
        [
            [
                group.get("name"),
                group.get("label"),
                ", ".join(group.get("columns") or []),
            ]
            for group in summary.get("feature_groups") or []
        ],
    )
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(
    payload: dict[str, Any],
    *,
    json_out: str | Path = DEFAULT_JSON_OUT,
    report_out: str | Path = DEFAULT_REPORT_OUT,
) -> tuple[Path, Path]:
    json_path = write_json_atomic(json_out, payload, trailing_newline=True)
    report_path = Path(report_out)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_markdown(payload), encoding="utf-8")
    return json_path, report_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit reanalysis sidecar coverage for a replay window.")
    parser.add_argument("--reanalysis-root", default=str(DEFAULT_REANALYSIS_ROOT))
    parser.add_argument("--target-start", default="")
    parser.add_argument("--target-end", default="")
    parser.add_argument("--required-groups", default=",".join(DEFAULT_REQUIRED_GROUPS))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_payload(
        reanalysis_root=args.reanalysis_root,
        target_start=args.target_start or None,
        target_end=args.target_end or None,
        required_groups=args.required_groups,
    )
    json_path, report_path = write_outputs(
        payload,
        json_out=args.json_out,
        report_out=args.report_out,
    )
    print(f"Reanalysis sidecar coverage audit: {payload['status']}")
    print(f"Wrote {json_path}")
    print(f"Wrote {report_path}")
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
