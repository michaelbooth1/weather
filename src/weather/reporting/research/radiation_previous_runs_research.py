"""Scratch-only acquisition of fixed-lead radiation for offline Tmax research.

The production mirror is read-only.  This module selects the latest admissible
``previous_day1`` baseline rows already present in that mirror, downloads the
matching Open-Meteo fixed-lead radiation fields, and writes a small derived data
root under an explicitly supplied scratch directory.  It never writes beneath
``data/`` and never changes a production collector.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import requests

from weather.io import (
    copy_file_atomic,
    request_with_retries,
    write_bytes_atomic,
    write_csv_rows_atomic,
    write_json_atomic,
    write_text_atomic,
)
from weather.market.market_registry import BUILTIN_SPECS, MarketSpec
from weather.reporting.formatting import markdown_table
from weather.reporting.research.offline_tmax_predictor_evaluation import (
    load_market_rows,
    resolve_paths_outside_read_only_root,
)
from weather.schema_registry import schema_version
from weather.sources.forecast_history import (
    PREVIOUS_RUNS_URL,
    RICH_FORECAST_COLUMNS,
    forecast_payload_hash,
    local_valid_datetime,
)
from weather.units import to_float


SCHEMA_VERSION = schema_version("radiation_previous_runs_research")
PREVIOUS_RUN_LEAD_DAYS = 1
API_TO_ROW_FIELD = {
    "shortwave_radiation_previous_day1": "shortwave_radiation",
    "direct_radiation_previous_day1": "direct_radiation",
    "diffuse_radiation_previous_day1": "diffuse_radiation",
    "cloud_cover_previous_day1": "cloud_cover",
}
HOURLY_PARAM = ",".join(API_TO_ROW_FIELD)
DEFAULT_PAUSE_SECONDS = 0.35
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_ATTEMPTS = 4


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: str | Path) -> str | None:
    path = Path(path)
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _station_root(root: Path, station: str) -> Path:
    lower = root / station.lower()
    upper = root / station.upper()
    return lower if lower.exists() or not upper.exists() else upper


def source_paths(data_root: str | Path, spec: MarketSpec) -> tuple[Path, Path]:
    data_root = Path(data_root)
    forecast = _station_root(data_root / "forecast_history", spec.icao) / "forecast_long.csv"
    settlement = _station_root(data_root / "wunderground", spec.icao) / "daily" / "daily_summary.csv"
    return forecast, settlement


def request_params(spec: MarketSpec, start_date: str, end_date: str) -> dict[str, Any]:
    return {
        "latitude": spec.lat,
        "longitude": spec.lon,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": HOURLY_PARAM,
        "timezone": spec.timezone,
    }


def prepared_url(params: Mapping[str, Any]) -> str:
    return str(requests.Request("GET", PREVIOUS_RUNS_URL, params=dict(params)).prepare().url)


def fetch_response_bytes(
    params: Mapping[str, Any],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
    request_get: Callable[..., Any] = requests.get,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[bytes, str, int]:
    """Fetch one idempotent request with repository-standard transient retries."""

    def once():
        response = request_get(PREVIOUS_RUNS_URL, params=dict(params), timeout=timeout_seconds)
        response.raise_for_status()
        return response

    response = request_with_retries(
        once,
        attempts=attempts,
        base_delay=0.5,
        sleep=sleep_fn,
    )
    return bytes(response.content), str(response.url), int(response.status_code)


def fetch_or_load_payload(
    *,
    raw_path: str | Path,
    params: Mapping[str, Any],
    refresh: bool = False,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
    request_get: Callable[..., Any] = requests.get,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Return payload, request provenance, and whether a network call occurred."""

    raw_path = Path(raw_path)
    requested_url = prepared_url(params)
    requested_at = None
    completed_at = None
    network_used = False
    if raw_path.exists() and not refresh:
        content = raw_path.read_bytes()
        final_url = requested_url
        status_code = 200
        cache_status = "reused"
    else:
        requested_at = utc_iso()
        content, final_url, status_code = fetch_response_bytes(
            params,
            timeout_seconds=timeout_seconds,
            attempts=attempts,
            request_get=request_get,
            sleep_fn=sleep_fn,
        )
        completed_at = utc_iso()
        write_bytes_atomic(raw_path, content)
        cache_status = "fetched"
        network_used = True
    payload = json.loads(content.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"unexpected non-object API payload at {raw_path}")
    return payload, {
        "endpoint": PREVIOUS_RUNS_URL,
        "requested_url": requested_url,
        "final_url": final_url,
        "params": dict(params),
        "requested_at_utc": requested_at,
        "completed_at_utc": completed_at,
        "status_code": status_code,
        "cache_status": cache_status,
        "raw_path": str(raw_path),
        "raw_size_bytes": len(content),
        "raw_sha256": sha256_bytes(content),
    }, network_used


def payload_hourly_index(payload: Mapping[str, Any], spec: MarketSpec) -> dict[str, dict[str, Any]]:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    output = {}
    for index, raw_time in enumerate(times):
        if not raw_time:
            continue
        valid_time = local_valid_datetime(raw_time, spec).isoformat()
        item = {}
        for api_field, row_field in API_TO_ROW_FIELD.items():
            values = hourly.get(api_field) or []
            item[row_field] = to_float(values[index] if index < len(values) else None)
        output[valid_time] = item
    return output


def enrich_selected_rows(
    source_forecast_path: str | Path,
    *,
    selected_rows: Sequence[Mapping[str, Any]],
    hourly_by_valid_time: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Retain selected baseline issues and overlay same-lead radiation fields."""

    selected_keys = {
        (
            str(row["target_date"]),
            str(row["selected_issue_time"]),
            str(row.get("source") or ""),
            str(row.get("source_model") or ""),
        )
        for row in selected_rows
    }
    output = []
    nonnull = Counter()
    complete_hours_by_date = Counter()
    row_counts_by_date = Counter()
    with Path(source_forecast_path).open("r", encoding="utf-8-sig", newline="") as handle:
        for source_row in csv.DictReader(handle):
            key = (
                str(source_row.get("target_date") or ""),
                str(source_row.get("issue_time") or ""),
                str(source_row.get("source") or ""),
                str(source_row.get("source_model") or ""),
            )
            if key not in selected_keys:
                continue
            row = dict(source_row)
            values = hourly_by_valid_time.get(str(row.get("valid_time") or "")) or {}
            for row_field in API_TO_ROW_FIELD.values():
                value = to_float(values.get(row_field))
                row[row_field] = "" if value is None else value
                if value is not None:
                    nonnull[row_field] += 1
            row["payload_hash"] = forecast_payload_hash(row)
            output.append(row)
            target_date = str(row.get("target_date") or "")
            row_counts_by_date[target_date] += 1
            if all(to_float(row.get(field)) is not None for field in API_TO_ROW_FIELD.values()):
                complete_hours_by_date[target_date] += 1
    output.sort(key=lambda row: (str(row.get("target_date")), str(row.get("valid_time"))))
    target_dates = sorted(row_counts_by_date)
    return output, {
        "selected_market_dates": len(selected_keys),
        "derived_rows": len(output),
        "nonnull_by_field": {
            field: int(nonnull[field]) for field in API_TO_ROW_FIELD.values()
        },
        "dates_with_any_complete_hour": sum(complete_hours_by_date[day] > 0 for day in target_dates),
        "dates_with_24_complete_hours": sum(
            complete_hours_by_date[day] >= 24 for day in target_dates
        ),
        "first_date": target_dates[0] if target_dates else None,
        "last_date": target_dates[-1] if target_dates else None,
    }


def _year_ranges(rows: Sequence[Mapping[str, Any]]) -> list[tuple[int, str, str]]:
    dates_by_year: dict[int, list[str]] = defaultdict(list)
    for row in rows:
        target_date = str(row.get("target_date") or "")[:10]
        if target_date:
            dates_by_year[int(target_date[:4])].append(target_date)
    return [
        (year, min(dates), max(dates))
        for year, dates in sorted(dates_by_year.items())
    ]


def _request_coverage(payload: Mapping[str, Any]) -> dict[str, Any]:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    return {
        "hourly_rows": len(times),
        "first_time": times[0] if times else None,
        "last_time": times[-1] if times else None,
        "nonnull_by_api_field": {
            field: sum(to_float(value) is not None for value in (hourly.get(field) or []))
            for field in API_TO_ROW_FIELD
        },
    }


def build_market_scratch_data(
    *,
    source_data_root: str | Path,
    output_root: str | Path,
    spec: MarketSpec,
    cutoff_local: str = "00:00",
    refresh: bool = False,
    pause_seconds: float = DEFAULT_PAUSE_SECONDS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
    request_get: Callable[..., Any] = requests.get,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any], bool]:
    source_data_root, guarded_roots = resolve_paths_outside_read_only_root(
        read_only_root=source_data_root,
        paths={
            "output_root": output_root,
            "raw_cache_root": Path(output_root) / "raw",
            "derived_data_root": Path(output_root) / "derived_data",
        },
    )
    output_root = guarded_roots["output_root"]
    source_forecast, source_settlement = source_paths(source_data_root, spec)
    selected, baseline_audit, _ = load_market_rows(
        data_root=source_data_root,
        spec=spec,
        family="radiation",
        cutoff_local=cutoff_local,
    )
    requests_provenance = []
    merged_hourly: dict[str, dict[str, Any]] = {}
    network_used = False
    errors = []
    for year, start_date, end_date in _year_ranges(selected):
        params = request_params(spec, start_date, end_date)
        raw_path = output_root / "raw" / spec.id / f"{year}.json"
        _, resolved_raw = resolve_paths_outside_read_only_root(
            read_only_root=source_data_root,
            paths={"raw_cache_file": raw_path},
        )
        raw_path = resolved_raw["raw_cache_file"]
        try:
            payload, request_record, fetched = fetch_or_load_payload(
                raw_path=raw_path,
                params=params,
                refresh=refresh,
                timeout_seconds=timeout_seconds,
                attempts=attempts,
                request_get=request_get,
                sleep_fn=sleep_fn,
            )
            request_record["coverage"] = _request_coverage(payload)
            requests_provenance.append(request_record)
            merged_hourly.update(payload_hourly_index(payload, spec))
            network_used = network_used or fetched
            if fetched and pause_seconds > 0:
                sleep_fn(float(pause_seconds))
        except Exception as exc:  # noqa: BLE001 - record per-year acquisition blocker and continue
            errors.append({
                "year": year,
                "start_date": start_date,
                "end_date": end_date,
                "requested_url": prepared_url(params),
                "error_type": type(exc).__name__,
                "error": str(exc),
            })

    enriched_rows, derived_coverage = enrich_selected_rows(
        source_forecast,
        selected_rows=selected,
        hourly_by_valid_time=merged_hourly,
    )
    derived_data_root = output_root / "derived_data"
    derived_forecast = (
        derived_data_root / "forecast_history" / spec.icao.lower() / "forecast_long.csv"
    )
    derived_settlement = (
        derived_data_root
        / "wunderground"
        / spec.icao.lower()
        / "daily"
        / "daily_summary.csv"
    )
    _, resolved_outputs = resolve_paths_outside_read_only_root(
        read_only_root=source_data_root,
        paths={
            "derived_forecast_file": derived_forecast,
            "derived_settlement_file": derived_settlement,
        },
    )
    derived_forecast = resolved_outputs["derived_forecast_file"]
    derived_settlement = resolved_outputs["derived_settlement_file"]
    write_csv_rows_atomic(derived_forecast, RICH_FORECAST_COLUMNS, enriched_rows)
    if source_settlement.exists():
        copy_file_atomic(source_settlement, derived_settlement)
    return {
        "market_id": spec.id,
        "station": spec.icao,
        "timezone": spec.timezone,
        "temperature_unit": spec.unit,
        "source_forecast": {
            "path": str(source_forecast),
            "sha256": sha256_file(source_forecast),
            "size_bytes": source_forecast.stat().st_size if source_forecast.exists() else None,
        },
        "source_settlement": {
            "path": str(source_settlement),
            "sha256": sha256_file(source_settlement),
            "size_bytes": source_settlement.stat().st_size if source_settlement.exists() else None,
        },
        "baseline_audit": baseline_audit,
        "request_count": len(requests_provenance),
        "requests": requests_provenance,
        "errors": errors,
        "derived": {
            **derived_coverage,
            "forecast_path": str(derived_forecast),
            "forecast_sha256": sha256_file(derived_forecast),
            "settlement_path": str(derived_settlement),
            "settlement_sha256": sha256_file(derived_settlement),
        },
    }, network_used


def build_scratch_backfill(
    *,
    source_data_root: str | Path,
    output_root: str | Path,
    cutoff_local: str = "00:00",
    refresh: bool = False,
    pause_seconds: float = DEFAULT_PAUSE_SECONDS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
    specs: Sequence[MarketSpec] = BUILTIN_SPECS,
    request_get: Callable[..., Any] = requests.get,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    source_data_root, guarded_roots = resolve_paths_outside_read_only_root(
        read_only_root=source_data_root,
        paths={
            "output_root": output_root,
            "raw_cache_root": Path(output_root) / "raw",
            "derived_data_root": Path(output_root) / "derived_data",
            "manifest_json": Path(output_root) / "manifest.json",
            "manifest_report": Path(output_root) / "manifest.md",
        },
    )
    output_root = guarded_roots["output_root"]
    markets = []
    network_used = False
    for spec in specs:
        market, fetched = build_market_scratch_data(
            source_data_root=source_data_root,
            output_root=output_root,
            spec=spec,
            cutoff_local=cutoff_local,
            refresh=refresh,
            pause_seconds=pause_seconds,
            timeout_seconds=timeout_seconds,
            attempts=attempts,
            request_get=request_get,
            sleep_fn=sleep_fn,
        )
        markets.append(market)
        network_used = network_used or fetched
    errors = [error for market in markets for error in market["errors"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "research_only": True,
        "source_data_root": str(source_data_root),
        "output_root": str(output_root),
        "derived_data_root": str(output_root / "derived_data"),
        "cutoff_local": cutoff_local,
        "issue_time_contract": (
            "baseline issue_time is explicit fixed_lead_day_offset and strictly before target-date cutoff; "
            "radiation uses matching Open-Meteo previous_day1 fixed-lead values"
        ),
        "endpoint": PREVIOUS_RUNS_URL,
        "hourly_parameter": HOURLY_PARAM,
        "lead_days": PREVIOUS_RUN_LEAD_DAYS,
        "refresh": bool(refresh),
        "pause_seconds": float(pause_seconds),
        "timeout_seconds": float(timeout_seconds),
        "attempts": int(attempts),
        "network_used": network_used,
        "source_mirror_mutated": False,
        "market_count": len(markets),
        "request_count": sum(market["request_count"] for market in markets),
        "error_count": len(errors),
        "derived_rows": sum(market["derived"]["derived_rows"] for market in markets),
        "dates_with_any_complete_hour": sum(
            market["derived"]["dates_with_any_complete_hour"] for market in markets
        ),
        "dates_with_24_complete_hours": sum(
            market["derived"]["dates_with_24_complete_hours"] for market in markets
        ),
        "markets": markets,
    }


def write_manifest_report(path: str | Path, payload: Mapping[str, Any]) -> Path:
    path = Path(path)
    lines = [
        "# Scratch Fixed-Lead Radiation Backfill",
        "",
        f"Generated: {payload['generated_at_utc']}",
        f"Schema: `{payload['schema_version']}`",
        "",
        "This acquisition is research-only. The production mirror was read-only; all raw and derived files are under scratch.",
        "",
        "## Contract",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Endpoint", payload["endpoint"]],
            ["Hourly parameter", payload["hourly_parameter"]],
            ["Lead", "previous_day1 / 24-hour fixed offset"],
            ["Local cutoff", payload["cutoff_local"]],
            ["Requests", payload["request_count"]],
            ["Errors", payload["error_count"]],
            ["Derived rows", payload["derived_rows"]],
            ["Dates with any complete hour", payload["dates_with_any_complete_hour"]],
            ["Dates with 24 complete hours", payload["dates_with_24_complete_hours"]],
        ],
    )
    lines += ["", "## Market Coverage", ""]
    lines += markdown_table(
        ["Market", "Requests", "Errors", "Selected dates", "Derived rows", "Any-complete dates", "24h-complete dates"],
        [
            [
                market["market_id"],
                market["request_count"],
                len(market["errors"]),
                market["derived"]["selected_market_dates"],
                market["derived"]["derived_rows"],
                market["derived"]["dates_with_any_complete_hour"],
                market["derived"]["dates_with_24_complete_hours"],
            ]
            for market in payload["markets"]
        ],
    )
    return write_text_atomic(path, "\n".join(lines) + "\n")


def run(args: argparse.Namespace) -> dict[str, Any]:
    source_data_root, guarded_paths = resolve_paths_outside_read_only_root(
        read_only_root=args.source_data_root,
        paths={
            "output_root": args.output_root,
            "raw_cache_root": Path(args.output_root) / "raw",
            "derived_data_root": Path(args.output_root) / "derived_data",
            "manifest_json": Path(args.output_root) / "manifest.json",
            "manifest_report": Path(args.output_root) / "manifest.md",
        },
    )
    output_root = guarded_paths["output_root"]
    payload = build_scratch_backfill(
        source_data_root=source_data_root,
        output_root=output_root,
        cutoff_local=args.cutoff_local,
        refresh=args.refresh,
        pause_seconds=args.pause_seconds,
        timeout_seconds=args.timeout_seconds,
        attempts=args.attempts,
    )
    manifest = guarded_paths["manifest_json"]
    write_json_atomic(manifest, payload)
    write_manifest_report(guarded_paths["manifest_report"], payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill fixed-lead radiation into a scratch-only derived forecast-history root."
    )
    parser.add_argument("--source-data-root", required=True, help="Read-only mirrored data root.")
    parser.add_argument("--output-root", required=True, help="Scratch output root.")
    parser.add_argument("--cutoff-local", default="00:00")
    parser.add_argument("--refresh", action="store_true", help="Refetch even when an exact raw cache file exists.")
    parser.add_argument("--pause-seconds", type=float, default=DEFAULT_PAUSE_SECONDS)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    return parser


def main(argv: list[str] | None = None) -> int:
    payload = run(build_parser().parse_args(argv))
    print(
        f"Scratch radiation backfill: {payload['market_count']} markets, "
        f"{payload['request_count']} requests, {payload['error_count']} errors, "
        f"{payload['dates_with_any_complete_hour']} supported market-dates"
    )
    return 0 if payload["error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
