"""Fleet coverage report for historical weather sources."""
import argparse
import csv
import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from weather.market.market_registry import all_specs, spec_for_id
from weather.schema_registry import schema_version
from weather.sources.noaa_ghcnh_history import GHCNHStore
from weather.sources.reanalysis_history import ReanalysisStore
from weather.sources.supplemental_stations import source_root, supplemental_sources
from weather.sources.wu_history import WundergroundHistoryStore, history_coverage, parse_date


SCHEMA_VERSION = schema_version("historical_coverage")
COVERAGE_DASHBOARD_SCHEMA_VERSION = schema_version("historical_coverage_dashboard")
DEFAULT_OUT = Path("data") / "backtest" / "historical_coverage.json"
DEFAULT_DASHBOARD_JSON = Path("data") / "backtest" / "historical_coverage_dashboard.json"
DEFAULT_DASHBOARD_REPORT = Path("data") / "backtest" / "historical_coverage_dashboard.md"
DEFAULT_DASHBOARD_CSV = Path("data") / "backtest" / "historical_coverage_dashboard.csv"
DEFAULT_DASHBOARD_PARQUET = Path("data") / "backtest" / "historical_coverage_dashboard.parquet"
SOURCE_FRESHNESS_SLAS = {
    "wu": {"mode": "date", "max_age_days": 2},
    "reanalysis": {"mode": "date", "max_age_days": 14},
    "ghcnh": {"mode": "year", "max_year_lag": 1},
    "ghcnh_supplemental": {"mode": "year", "max_year_lag": 1},
}
DASHBOARD_COLUMNS = [
    "market_id",
    "city",
    "source",
    "source_role",
    "station",
    "expected_count",
    "covered_count",
    "missing_count",
    "source_unavailable_count",
    "raw_only_normalizable_count",
    "latest_covered",
    "freshness_mode",
    "freshness_age",
    "freshness_sla",
    "freshness_status",
    "coverage_status",
    "status",
    "manifest_exists",
    "daily_summary_exists",
    "data_root",
    "supplemental_source_id",
]


def wu_store(spec):
    return WundergroundHistoryStore(
        spec.data_root,
        station_icao=spec.icao,
        station_name=spec.city_label,
        history_id=spec.wu_history_id,
        tz=spec.tz,
        unit=spec.display_unit,
        wu_units=spec.wu_units,
    )


def ghcnh_supplemental_coverage(spec, start_year=None, end_year=None, registry=None):
    rows = []
    for source in supplemental_sources(spec.id, source_type="noaa_ghcnh", registry=registry):
        coverage = GHCNHStore(spec, source_root(source)).coverage(start_year, end_year)
        rows.append({
            "source_id": source.get("source_id"),
            "source_type": source.get("source_type"),
            "source_role": source.get("source_role"),
            "station_id": source.get("station_id"),
            "station_name": source.get("station_name"),
            "root_path": source.get("root_path"),
            "distance_from_canonical_km": source.get("distance_from_canonical_km"),
            "validation_status": source.get("validation_status"),
            "adopted_date_windows": source.get("adopted_date_windows"),
            "reason_for_adoption": source.get("reason_for_adoption"),
            "coverage": coverage,
        })
    return rows


def source_coverage(spec, start_date=None, end_date=None, registry=None):
    start_year = start_date.year if start_date else None
    end_year = end_date.year if end_date else None
    return {
        "market_id": spec.id,
        "city": spec.city_label,
        "station": spec.icao,
        "unit": spec.display_unit,
        "supplemental_sources": {
            "ghcnh": ghcnh_supplemental_coverage(spec, start_year, end_year, registry=registry),
        },
        "sources": {
            "wu": history_coverage(wu_store(spec), start_date, end_date),
            "ghcnh": GHCNHStore(spec).coverage(start_year, end_year),
            "reanalysis": ReanalysisStore(spec).coverage(start_date, end_date),
        },
    }


def fleet_coverage(market_ids=None, start_date=None, end_date=None, registry=None):
    ids = set(market_ids or [])
    specs = [spec for spec in all_specs() if not ids or spec.id in ids]
    return {
        "schema_version": SCHEMA_VERSION,
        "markets": [source_coverage(spec, start_date, end_date, registry=registry) for spec in specs],
    }


def _status_worst(*statuses):
    rank = {"OK": 0, "WARN": 1, "CRITICAL": 2}
    values = [status for status in statuses if status]
    if not values:
        return "OK"
    return max(values, key=lambda status: rank.get(status, -1))


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _latest_for_source(source, coverage):
    if source == "reanalysis":
        return (
            coverage.get("last_normalized_date")
            or coverage.get("last_raw_normalizable_date")
            or coverage.get("last_raw_date")
        )
    if source == "wu":
        return coverage.get("last_raw_date")
    raw_years = coverage.get("raw_years") or []
    if raw_years:
        return str(max(int(year) for year in raw_years))
    return coverage.get("last_normalized_date") or coverage.get("last_raw_date")


def _expected_covered_missing(source, coverage):
    if source in ("ghcnh", "ghcnh_supplemental"):
        expected = len(coverage.get("expected_years") or coverage.get("raw_years") or [])
        covered = len(coverage.get("raw_years") or [])
        missing = len(coverage.get("missing_years") or [])
        unavailable = int(coverage.get("source_unavailable_year_count") or 0)
        return expected, covered, missing, unavailable
    expected = int(coverage.get("expected_days") or 0)
    if source == "reanalysis":
        covered = int(coverage.get("normalized_daily_days") or coverage.get("covered_days") or 0)
    else:
        covered = int(coverage.get("raw_days") or coverage.get("covered_days") or 0)
    missing = int(coverage.get("missing_days") or 0)
    unavailable = int(coverage.get("source_unavailable_days") or 0)
    return expected, covered, missing, unavailable


def _freshness_status(source, coverage, as_of_date, slas):
    sla = (slas or {}).get(source) or {}
    mode = sla.get("mode")
    latest = _latest_for_source(source, coverage)
    if not mode:
        return latest, "", None, None, "OK"
    if mode == "year":
        years = coverage.get("raw_years") or []
        if not years:
            return latest, "year", None, f"{sla.get('max_year_lag')}y", "CRITICAL"
        newest = max(int(year) for year in years)
        lag = int(as_of_date.year) - newest
        max_lag = int(sla.get("max_year_lag", 1))
        status = "OK" if lag <= max_lag else ("WARN" if lag <= max_lag + 1 else "CRITICAL")
        return str(newest), "year", lag, f"{max_lag}y", status
    latest_date = _parse_date(latest)
    if latest_date is None:
        return latest, "date", None, f"{sla.get('max_age_days')}d", "CRITICAL"
    age = max(0, (as_of_date - latest_date).days)
    max_age = int(sla.get("max_age_days", 0))
    status = "OK" if age <= max_age else ("WARN" if age <= max_age * 2 else "CRITICAL")
    return latest_date.isoformat(), "date", age, f"{max_age}d", status


def _coverage_status(coverage, missing_count):
    if not coverage.get("manifest_exists") or not coverage.get("daily_summary_exists"):
        return "CRITICAL"
    if int(coverage.get("raw_only_normalizable_day_count") or 0) > 0:
        return "WARN"
    if int(missing_count or 0) > 0:
        return "WARN"
    return "OK"


def _dashboard_row(market, source, coverage, as_of_date, slas, source_role="canonical", supplemental_id=""):
    expected, covered, missing, unavailable = _expected_covered_missing(source, coverage)
    latest, freshness_mode, freshness_age, freshness_sla, freshness_status = _freshness_status(
        source,
        coverage,
        as_of_date,
        slas,
    )
    coverage_status = _coverage_status(coverage, missing)
    status = _status_worst(coverage_status, freshness_status)
    return {
        "market_id": market.get("market_id"),
        "city": market.get("city"),
        "source": source,
        "source_role": source_role,
        "station": coverage.get("station"),
        "expected_count": expected,
        "covered_count": covered,
        "missing_count": missing,
        "source_unavailable_count": unavailable,
        "raw_only_normalizable_count": int(coverage.get("raw_only_normalizable_day_count") or 0),
        "latest_covered": latest,
        "freshness_mode": freshness_mode,
        "freshness_age": freshness_age,
        "freshness_sla": freshness_sla,
        "freshness_status": freshness_status,
        "coverage_status": coverage_status,
        "status": status,
        "manifest_exists": bool(coverage.get("manifest_exists")),
        "daily_summary_exists": bool(coverage.get("daily_summary_exists")),
        "data_root": coverage.get("data_root"),
        "supplemental_source_id": supplemental_id,
    }


def coverage_dashboard(payload, as_of=None, slas=None):
    as_of_date = _parse_date(as_of) or datetime.now(timezone.utc).date()
    slas = slas or SOURCE_FRESHNESS_SLAS
    rows = []
    for market in payload.get("markets") or []:
        for source, coverage in sorted((market.get("sources") or {}).items()):
            rows.append(_dashboard_row(market, source, coverage or {}, as_of_date, slas))
        for item in ((market.get("supplemental_sources") or {}).get("ghcnh") or []):
            coverage = item.get("coverage") or {}
            rows.append(_dashboard_row(
                market,
                "ghcnh_supplemental",
                coverage,
                as_of_date,
                slas,
                source_role=item.get("source_role") or "supplemental",
                supplemental_id=item.get("source_id") or "",
            ))
    status_counts = Counter(row["status"] for row in rows)
    source_counts = Counter(f"{row['source']}:{row['status']}" for row in rows)
    return {
        "schema_version": COVERAGE_DASHBOARD_SCHEMA_VERSION,
        "coverage_schema_version": payload.get("schema_version"),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "as_of_date": as_of_date.isoformat(),
        "source_freshness_slas": slas,
        "summary": {
            "row_count": len(rows),
            "status_counts": dict(sorted(status_counts.items())),
            "source_status_counts": dict(sorted(source_counts.items())),
        },
        "rows": rows,
    }


def _markdown_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join("" if value is None else str(value) for value in row) + " |")
    return lines


def dashboard_markdown(dashboard):
    lines = [
        "# Historical Coverage Dashboard",
        "",
        f"Generated: `{dashboard.get('generated_at_utc')}`",
        f"As of: `{dashboard.get('as_of_date')}`",
        f"Schema: `{dashboard.get('schema_version')}`",
        "",
        "## Summary",
        "",
    ]
    summary = dashboard.get("summary") or {}
    lines += _markdown_table(
        ["Status", "Rows"],
        sorted((summary.get("status_counts") or {}).items()),
    )
    problem_rows = [row for row in dashboard.get("rows") or [] if row.get("status") != "OK"]
    if problem_rows:
        lines += ["", "## Gaps And Freshness Alerts", ""]
        lines += _markdown_table(
            ["Market", "Source", "Status", "Coverage", "Freshness", "Missing", "Latest", "SLA"],
            [
                [
                    row.get("market_id"),
                    row.get("source"),
                    row.get("status"),
                    row.get("coverage_status"),
                    row.get("freshness_status"),
                    row.get("missing_count"),
                    row.get("latest_covered"),
                    row.get("freshness_sla"),
                ]
                for row in problem_rows
            ],
        )
    lines += ["", "## All Sources", ""]
    lines += _markdown_table(
        ["Market", "Source", "Role", "Covered", "Expected", "Missing", "Latest", "Status"],
        [
            [
                row.get("market_id"),
                row.get("source"),
                row.get("source_role"),
                row.get("covered_count"),
                row.get("expected_count"),
                row.get("missing_count"),
                row.get("latest_covered"),
                row.get("status"),
            ]
            for row in dashboard.get("rows") or []
        ],
    )
    return "\n".join(lines) + "\n"


def write_dashboard_csv(rows, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DASHBOARD_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_dashboard_parquet(rows, out_path):
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas is required for parquet dashboard output") from exc
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=DASHBOARD_COLUMNS).to_parquet(out_path, index=False)


def write_dashboard_outputs(dashboard, json_out=None, markdown_out=None, csv_out=None, parquet_out=None):
    if json_out:
        write_report(dashboard, json_out)
    if markdown_out:
        path = Path(markdown_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dashboard_markdown(dashboard), encoding="utf-8")
    if csv_out:
        write_dashboard_csv(dashboard.get("rows") or [], csv_out)
    if parquet_out:
        write_dashboard_parquet(dashboard.get("rows") or [], parquet_out)


def write_report(payload, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_report(args):
    market_ids = [item.strip() for item in args.markets.split(",") if item.strip()]
    # Validate names early so typos do not silently produce a partial fleet.
    for market_id in market_ids:
        spec_for_id(market_id)
    start = parse_date(args.start) if args.start else None
    end = parse_date(args.end) if args.end else None
    payload = fleet_coverage(market_ids, start, end)
    write_report(payload, args.out)
    print(f"Wrote historical coverage report to {args.out}")
    if args.dashboard_out or args.dashboard_json_out or args.dashboard_csv_out or args.dashboard_parquet_out:
        dashboard = coverage_dashboard(payload, as_of=args.as_of)
        write_dashboard_outputs(
            dashboard,
            json_out=args.dashboard_json_out,
            markdown_out=args.dashboard_out,
            csv_out=args.dashboard_csv_out,
            parquet_out=args.dashboard_parquet_out,
        )
        if args.dashboard_json_out:
            print(f"Wrote coverage dashboard JSON to {args.dashboard_json_out}")
        if args.dashboard_out:
            print(f"Wrote coverage dashboard report to {args.dashboard_out}")
        if args.dashboard_csv_out:
            print(f"Wrote coverage dashboard CSV to {args.dashboard_csv_out}")
        if args.dashboard_parquet_out:
            print(f"Wrote coverage dashboard Parquet to {args.dashboard_parquet_out}")
    for market in payload["markets"]:
        bits = []
        for source, coverage in market["sources"].items():
            missing = coverage.get("missing_days", coverage.get("missing_years", []))
            if isinstance(missing, list):
                missing_text = str(len(missing))
            else:
                missing_text = str(missing)
            bits.append(f"{source}:missing={missing_text}")
        supplemental = (market.get("supplemental_sources") or {}).get("ghcnh") or []
        if supplemental:
            bits.append(f"ghcnh_supplemental={len(supplemental)}")
        print(f"{market['market_id']}: " + ", ".join(bits))


def cmd_dashboard(args):
    if args.coverage_json:
        payload = json.loads(Path(args.coverage_json).read_text(encoding="utf-8"))
    else:
        market_ids = [item.strip() for item in args.markets.split(",") if item.strip()]
        for market_id in market_ids:
            spec_for_id(market_id)
        start = parse_date(args.start) if args.start else None
        end = parse_date(args.end) if args.end else None
        payload = fleet_coverage(market_ids, start, end)
    dashboard = coverage_dashboard(payload, as_of=args.as_of)
    write_dashboard_outputs(
        dashboard,
        json_out=args.json_out,
        markdown_out=args.out,
        csv_out=args.csv_out,
        parquet_out=args.parquet_out,
    )
    print(f"Wrote historical coverage dashboard to {args.out}")
    if args.json_out:
        print(f"Wrote dashboard JSON to {args.json_out}")
    if args.csv_out:
        print(f"Wrote dashboard CSV to {args.csv_out}")
    if args.parquet_out:
        print(f"Wrote dashboard Parquet to {args.parquet_out}")


def build_parser():
    parser = argparse.ArgumentParser(description="Report historical-source coverage across markets.")
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report")
    report.add_argument("--markets", default="")
    report.add_argument("--start", default="")
    report.add_argument("--end", default="")
    report.add_argument("--out", default=str(DEFAULT_OUT))
    report.add_argument("--as-of", default="")
    report.add_argument("--dashboard-out", default="")
    report.add_argument("--dashboard-json-out", default="")
    report.add_argument("--dashboard-csv-out", default="")
    report.add_argument("--dashboard-parquet-out", default="")
    report.set_defaults(func=cmd_report)

    dashboard = sub.add_parser("dashboard")
    dashboard.add_argument("--coverage-json", default="")
    dashboard.add_argument("--markets", default="")
    dashboard.add_argument("--start", default="")
    dashboard.add_argument("--end", default="")
    dashboard.add_argument("--as-of", default="")
    dashboard.add_argument("--out", default=str(DEFAULT_DASHBOARD_REPORT))
    dashboard.add_argument("--json-out", default=str(DEFAULT_DASHBOARD_JSON))
    dashboard.add_argument("--csv-out", default=str(DEFAULT_DASHBOARD_CSV))
    dashboard.add_argument("--parquet-out", default=str(DEFAULT_DASHBOARD_PARQUET))
    dashboard.set_defaults(func=cmd_dashboard)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
