"""Guardrails that keep canonical history separate from supplemental views."""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path

from weather.market.market_registry import all_specs, spec_for_id
from weather.sources.supplemental_station_validation import (
    DEFAULT_OUT as DEFAULT_SUPPLEMENTAL_VALIDATION_OUT,
    load_validation_report,
    promotion_gate_for_source,
)
from weather.sources.supplemental_stations import load_registry, source_root, supplemental_sources
from weather.paths import REPO_ROOT, relative_to_repo


CANONICAL_GUARDRAIL_SCHEMA_VERSION = "canonical_history_guardrails_v0.1"
COMPOSITE_VIEW_SCHEMA_VERSION = "ghcnh_composite_daily_view_v0.1"
DEFAULT_OUT = REPO_ROOT / "data" / "backtest" / "canonical_history_guardrails.json"
DEFAULT_COMPOSITE_ROOT = REPO_ROOT / "data" / "backtest" / "composite_history"


def parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def canonical_daily_path(spec, source):
    station = spec.icao.lower()
    if source == "ghcnh":
        return REPO_ROOT / "data" / "noaa_ghcnh" / station / "daily" / "daily_summary.csv"
    if source == "wu":
        return REPO_ROOT / "data" / "wunderground" / station / "daily" / "daily_summary.csv"
    if source == "metar":
        return REPO_ROOT / "data" / "metar" / station / "daily" / "daily_summary.csv"
    if source == "reanalysis":
        return REPO_ROOT / "data" / "reanalysis" / station / "daily" / "daily_summary.csv"
    raise KeyError(source)


def read_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def canonical_station_id(spec, source):
    if source in {"wu", "metar", "reanalysis"}:
        return spec.icao.upper()
    if source == "ghcnh":
        station = read_json(REPO_ROOT / "data" / "noaa_ghcnh" / spec.icao.lower() / "station.json")
        return (
            station.get("GHCN_ID")
            or station.get("ID")
            or station.get("station_id")
            or station.get("Station_ID")
        )
    return None


def read_daily_rows(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _row_date(row):
    value = row.get("local_date") or row.get("date")
    try:
        return parse_date(value)
    except (TypeError, ValueError):
        return None


def _in_window(row, start=None, end=None):
    local_date = _row_date(row)
    if local_date is None:
        return False
    start = parse_date(start)
    end = parse_date(end)
    if start and local_date < start:
        return False
    if end and local_date > end:
        return False
    return True


def supplemental_station_ids(spec, registry=None):
    return {
        source.get("station_id")
        for source in supplemental_sources(spec.id, registry=registry)
        if source.get("station_id")
    }


def canonical_daily_violations(spec, source="ghcnh", path=None, registry=None, limit=25):
    path = Path(path) if path else canonical_daily_path(spec, source)
    expected_station = canonical_station_id(spec, source)
    supplemental_ids = supplemental_station_ids(spec, registry=registry)
    violations = []
    for line_number, row in enumerate(read_daily_rows(path), start=2):
        role = row.get("source_role") or "canonical"
        station = row.get("station") or row.get("station_id") or row.get("Station")
        supplemental_source_id = row.get("supplemental_source_id") or ""
        supplemental_station_id = row.get("supplemental_station_id") or ""
        if role not in {"", "canonical"}:
            violations.append({
                "type": "non_canonical_source_role",
                "line_number": line_number,
                "local_date": row.get("local_date"),
                "source_role": role,
            })
        if supplemental_source_id or supplemental_station_id:
            violations.append({
                "type": "supplemental_lineage_in_canonical_csv",
                "line_number": line_number,
                "local_date": row.get("local_date"),
                "supplemental_source_id": supplemental_source_id,
                "supplemental_station_id": supplemental_station_id,
            })
        if station and station in supplemental_ids:
            violations.append({
                "type": "registered_supplemental_station_in_canonical_csv",
                "line_number": line_number,
                "local_date": row.get("local_date"),
                "station": station,
            })
        if expected_station and station and station != expected_station:
            violations.append({
                "type": "unexpected_canonical_station",
                "line_number": line_number,
                "local_date": row.get("local_date"),
                "station": station,
                "expected_station": expected_station,
            })
        if len(violations) >= limit:
            break
    return {
        "source": source,
        "path": relative_to_repo(path),
        "exists": path.exists(),
        "expected_station_id": expected_station,
        "violation_count": len(violations),
        "violations": violations,
    }


def canonical_guardrail_report(market_ids=None, registry=None, sources=("ghcnh",)):
    registry = registry if registry is not None else load_registry()
    ids = set(market_ids or [])
    markets = []
    for spec in all_specs():
        if ids and spec.id not in ids:
            continue
        source_rows = [
            canonical_daily_violations(spec, source, registry=registry)
            for source in sources
        ]
        markets.append({
            "market_id": spec.id,
            "city": spec.city_label,
            "station": spec.icao,
            "sources": source_rows,
            "violation_count": sum(row.get("violation_count", 0) for row in source_rows),
        })
    violation_count = sum(market.get("violation_count", 0) for market in markets)
    return {
        "schema_version": CANONICAL_GUARDRAIL_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "markets": markets,
        "summary": {
            "market_count": len(markets),
            "violation_count": violation_count,
            "status": "PASS" if violation_count == 0 else "FAIL",
        },
    }


def _lineage_row(row, lineage):
    out = {
        "view_schema_version": COMPOSITE_VIEW_SCHEMA_VERSION,
        "lineage_source_role": lineage.get("source_role"),
        "lineage_source_id": lineage.get("source_id"),
        "lineage_station_id": lineage.get("station_id"),
        "lineage_distance_from_canonical_km": lineage.get("distance_from_canonical_km"),
        "lineage_validation_status": lineage.get("validation_status"),
        "lineage_promotion_state": lineage.get("promotion_state"),
        "lineage_root_path": lineage.get("root_path"),
        "lineage_daily_path": lineage.get("daily_path"),
    }
    out.update(row)
    return out


def build_ghcnh_composite_view(
    spec,
    registry=None,
    validation_report=None,
    validation_path=DEFAULT_SUPPLEMENTAL_VALIDATION_OUT,
    start=None,
    end=None,
    include_unvalidated=False,
):
    registry = registry if registry is not None else load_registry()
    validation_report = (
        validation_report
        if validation_report is not None
        else load_validation_report(validation_path)
    )
    rows = []
    canonical_path = canonical_daily_path(spec, "ghcnh")
    canonical_lineage = {
        "source_role": "canonical",
        "source_id": "ghcnh_canonical",
        "station_id": canonical_station_id(spec, "ghcnh") or spec.icao.upper(),
        "distance_from_canonical_km": 0.0,
        "validation_status": "canonical",
        "promotion_state": "canonical",
        "root_path": relative_to_repo(canonical_path.parents[1]),
        "daily_path": relative_to_repo(canonical_path),
    }
    for row in read_daily_rows(canonical_path):
        if _in_window(row, start=start, end=end):
            rows.append(_lineage_row(row, canonical_lineage))
    for source in supplemental_sources(spec.id, source_type="noaa_ghcnh", registry=registry):
        gate = promotion_gate_for_source(
            source,
            validation_report=validation_report,
            validation_path=validation_path,
        )
        if not gate.get("ok") and not include_unvalidated:
            continue
        root = source_root(source)
        daily_path = root / "daily" / "daily_summary.csv"
        lineage = {
            "source_role": "supplemental",
            "source_id": source.get("source_id"),
            "station_id": source.get("station_id"),
            "distance_from_canonical_km": source.get("distance_from_canonical_km"),
            "validation_status": source.get("validation_status"),
            "promotion_state": gate.get("promotion_state"),
            "root_path": relative_to_repo(root),
            "daily_path": relative_to_repo(daily_path),
        }
        for row in read_daily_rows(daily_path):
            if _in_window(row, start=start, end=end):
                rows.append(_lineage_row(row, lineage))
    return sorted(rows, key=lambda item: (
        item.get("local_date") or "",
        item.get("lineage_source_role") != "canonical",
        item.get("lineage_source_id") or "",
    ))


def write_composite_daily_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    base = [
        "view_schema_version",
        "lineage_source_role",
        "lineage_source_id",
        "lineage_station_id",
        "lineage_distance_from_canonical_km",
        "lineage_validation_status",
        "lineage_promotion_state",
        "lineage_root_path",
        "lineage_daily_path",
    ]
    fieldnames = list(base)
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit canonical history provenance guardrails.")
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--markets", default="")
    audit.add_argument("--out", default=str(DEFAULT_OUT))
    composite = sub.add_parser("composite-ghcnh")
    composite.add_argument("--market", required=True)
    composite.add_argument("--start", default="")
    composite.add_argument("--end", default="")
    composite.add_argument("--validation", default=str(DEFAULT_SUPPLEMENTAL_VALIDATION_OUT))
    composite.add_argument("--out", default="")
    args = parser.parse_args(argv)

    if args.command == "audit":
        market_ids = [item.strip() for item in args.markets.split(",") if item.strip()]
        for market_id in market_ids:
            spec_for_id(market_id)
        payload = canonical_guardrail_report(market_ids=market_ids)
        out = write_json(args.out, payload)
        print(f"Wrote canonical history guardrail audit to {out}")
        print(f"Status: {payload['summary']['status']} violations={payload['summary']['violation_count']}")
        return 0 if payload["summary"]["status"] == "PASS" else 2

    spec = spec_for_id(args.market)
    start = parse_date(args.start)
    end = parse_date(args.end)
    rows = build_ghcnh_composite_view(
        spec,
        validation_path=Path(args.validation) if args.validation else None,
        start=start,
        end=end,
    )
    out = Path(args.out) if args.out else DEFAULT_COMPOSITE_ROOT / spec.id / "ghcnh_composite_daily.csv"
    write_composite_daily_csv(out, rows)
    print(f"Wrote {len(rows)} composite rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
