"""Prepare high-AOD/high-PM smoke slices from archived Open-Meteo AQ rows."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.io import write_json_atomic
from weather.market.market_registry import all_specs, spec_for_id
from weather.model.feature_store import (
    SMOKE_AEROSOL_OPTICAL_DEPTH_THRESHOLD,
    SMOKE_DUST_THRESHOLD_UG_M3,
    SMOKE_PM2_5_THRESHOLD_UG_M3,
)
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, markdown_table


SCHEMA_VERSION = "forecast_smoke_slice_prep_v0.1"
DEFAULT_OPEN_METEO_ARCHIVE_ROOT = data_path() / "open_meteo_archives"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item188_forecast_smoke_slice_prep.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item188_forecast_smoke_slice_prep_report.md"
DEFAULT_PM10_THRESHOLD_UG_M3 = 55.0


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values):
    values = [value for value in values if value is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _max(values):
    values = [value for value in values if value is not None]
    if not values:
        return None
    return max(values)


def parse_markets(value: str | None):
    values = [item.strip() for item in str(value or "").split(",") if item.strip()]
    if not values:
        return all_specs()
    return [spec_for_id(item) for item in values]


def read_air_quality_rows(archive_root: str | Path, specs=None) -> list[dict[str, Any]]:
    root = Path(archive_root)
    rows = []
    for spec in specs or all_specs():
        path = root / spec.icao.lower() / "air_quality" / "hourly.csv"
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                copy = dict(row)
                copy["market_id"] = copy.get("market") or spec.id
                copy["station"] = copy.get("station") or spec.icao
                copy["source_path"] = str(path)
                rows.append(copy)
    return rows


def _slice_label(*, high_aod: bool, high_pm: bool, high_dust: bool) -> str:
    if high_aod and high_pm:
        return "high_aod_high_pm"
    if high_aod:
        return "high_aod"
    if high_pm:
        return "high_pm"
    if high_dust:
        return "high_dust"
    return "normal"


def daily_smoke_slice_rows(
    hourly_rows: list[dict[str, Any]],
    *,
    pm2_5_threshold: float = SMOKE_PM2_5_THRESHOLD_UG_M3,
    pm10_threshold: float = DEFAULT_PM10_THRESHOLD_UG_M3,
    aod_threshold: float = SMOKE_AEROSOL_OPTICAL_DEPTH_THRESHOLD,
    dust_threshold: float = SMOKE_DUST_THRESHOLD_UG_M3,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in hourly_rows:
        market_id = row.get("market_id") or row.get("market")
        target_date = row.get("target_date")
        if not market_id or not target_date:
            continue
        grouped[(str(market_id), str(target_date))].append(row)

    out = []
    for (market_id, target_date), rows in sorted(grouped.items()):
        pm2_5_values = [_safe_float(row.get("pm2_5")) for row in rows]
        pm10_values = [_safe_float(row.get("pm10")) for row in rows]
        aod_values = [_safe_float(row.get("aerosol_optical_depth")) for row in rows]
        dust_values = [_safe_float(row.get("dust")) for row in rows]
        pm2_5_max = _max(pm2_5_values)
        pm10_max = _max(pm10_values)
        aod_max = _max(aod_values)
        dust_max = _max(dust_values)
        high_pm = (
            (pm2_5_max is not None and pm2_5_max >= pm2_5_threshold)
            or (pm10_max is not None and pm10_max >= pm10_threshold)
        )
        high_aod = aod_max is not None and aod_max >= aod_threshold
        high_dust = dust_max is not None and dust_max >= dust_threshold
        label = _slice_label(high_aod=high_aod, high_pm=high_pm, high_dust=high_dust)
        out.append({
            "market_id": market_id,
            "target_date": target_date,
            "station": rows[0].get("station"),
            "source": "open_meteo_air_quality",
            "row_count": len(rows),
            "pm2_5_max": pm2_5_max,
            "pm2_5_mean": _mean(pm2_5_values),
            "pm10_max": pm10_max,
            "pm10_mean": _mean(pm10_values),
            "aerosol_optical_depth_max": aod_max,
            "aerosol_optical_depth_mean": _mean(aod_values),
            "dust_max": dust_max,
            "dust_mean": _mean(dust_values),
            "high_pm_flag": bool(high_pm),
            "high_aod_flag": bool(high_aod),
            "high_dust_flag": bool(high_dust),
            "high_aod_high_pm_flag": bool(high_aod and high_pm),
            "high_smoke_flag": bool(high_aod or high_pm or high_dust),
            "smoke_slice": label,
        })
    return out


def slice_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(row.get("smoke_slice") or "unknown" for row in rows)
    high_smoke = [row for row in rows if row.get("high_smoke_flag")]
    high_aod_high_pm = [row for row in rows if row.get("high_aod_high_pm_flag")]
    by_market = Counter(row.get("market_id") for row in rows)
    return {
        "day_count": len(rows),
        "high_smoke_day_count": len(high_smoke),
        "high_aod_high_pm_day_count": len(high_aod_high_pm),
        "slice_counts": dict(sorted(counts.items())),
        "market_counts": dict(sorted(by_market.items())),
        "replay_join_keys": ["market_id", "target_date"],
        "candidate_slice_rows": [
            {
                "group": "high_smoke",
                "n": len(high_smoke),
                "filter": "high_smoke_flag == true",
            },
            {
                "group": "high_aod_high_pm",
                "n": len(high_aod_high_pm),
                "filter": "high_aod_high_pm_flag == true",
            },
        ],
    }


def build_payload(
    *,
    archive_root=DEFAULT_OPEN_METEO_ARCHIVE_ROOT,
    markets="",
    pm2_5_threshold=SMOKE_PM2_5_THRESHOLD_UG_M3,
    pm10_threshold=DEFAULT_PM10_THRESHOLD_UG_M3,
    aod_threshold=SMOKE_AEROSOL_OPTICAL_DEPTH_THRESHOLD,
    dust_threshold=SMOKE_DUST_THRESHOLD_UG_M3,
    generated_at_utc=None,
) -> dict[str, Any]:
    specs = parse_markets(markets)
    hourly = read_air_quality_rows(archive_root, specs=specs)
    rows = daily_smoke_slice_rows(
        hourly,
        pm2_5_threshold=pm2_5_threshold,
        pm10_threshold=pm10_threshold,
        aod_threshold=aod_threshold,
        dust_threshold=dust_threshold,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "archive_root": str(Path(archive_root)),
        "markets": [spec.id for spec in specs],
        "thresholds": {
            "pm2_5": pm2_5_threshold,
            "pm10": pm10_threshold,
            "aerosol_optical_depth": aod_threshold,
            "dust": dust_threshold,
        },
        "summary": slice_summary(rows),
        "rows": rows,
    }


def write_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    summary = payload.get("summary") or {}
    thresholds = payload.get("thresholds") or {}
    lines = [
        "# Forecast Smoke Slice Prep",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Archive root: `{payload.get('archive_root')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Days", summary.get("day_count")],
            ["High-smoke days", summary.get("high_smoke_day_count")],
            ["High-AOD/high-PM days", summary.get("high_aod_high_pm_day_count")],
            ["Join keys", ", ".join(summary.get("replay_join_keys") or [])],
            ["PM2.5 threshold", fmt_num(thresholds.get("pm2_5"), 2)],
            ["PM10 threshold", fmt_num(thresholds.get("pm10"), 2)],
            ["AOD threshold", fmt_num(thresholds.get("aerosol_optical_depth"), 2)],
            ["Dust threshold", fmt_num(thresholds.get("dust"), 2)],
        ],
    )
    lines += ["", "## Slice Counts", ""]
    lines += markdown_table(
        ["Slice", "Days"],
        [[key, value] for key, value in (summary.get("slice_counts") or {}).items()],
    )
    lines += ["", "## Candidate Slice Rows", ""]
    lines += markdown_table(
        ["Group", "Rows", "Filter"],
        [
            [row.get("group"), row.get("n"), row.get("filter")]
            for row in summary.get("candidate_slice_rows") or []
        ],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(args):
    payload = build_payload(
        archive_root=args.archive_root,
        markets=args.markets,
        pm2_5_threshold=args.pm2_5_threshold,
        pm10_threshold=args.pm10_threshold,
        aod_threshold=args.aod_threshold,
        dust_threshold=args.dust_threshold,
    )
    write_json_atomic(args.out, payload, trailing_newline=True)
    write_report(args.report, payload)
    return payload


def build_parser():
    parser = argparse.ArgumentParser(description="Prepare high-AOD/high-PM smoke slices from Open-Meteo AQ archives.")
    parser.add_argument("--archive-root", default=str(DEFAULT_OPEN_METEO_ARCHIVE_ROOT))
    parser.add_argument("--markets", default="")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--pm2-5-threshold", type=float, default=SMOKE_PM2_5_THRESHOLD_UG_M3)
    parser.add_argument("--pm10-threshold", type=float, default=DEFAULT_PM10_THRESHOLD_UG_M3)
    parser.add_argument("--aod-threshold", type=float, default=SMOKE_AEROSOL_OPTICAL_DEPTH_THRESHOLD)
    parser.add_argument("--dust-threshold", type=float, default=SMOKE_DUST_THRESHOLD_UG_M3)
    return parser


def main(argv=None):
    payload = run(build_parser().parse_args(argv))
    summary = payload["summary"]
    print(
        "Forecast smoke slice prep: "
        f"{summary['high_smoke_day_count']} high-smoke day(s), "
        f"{summary['high_aod_high_pm_day_count']} high-AOD/high-PM day(s)"
    )


if __name__ == "__main__":
    main()
