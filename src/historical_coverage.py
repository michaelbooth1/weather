"""Fleet coverage report for historical weather sources."""
import argparse
import json
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_registry import all_specs, spec_for_id  # noqa: E402
from noaa_ghcnh_history import GHCNHStore  # noqa: E402
from reanalysis_history import ReanalysisStore  # noqa: E402
from wu_history import WundergroundHistoryStore, history_coverage, parse_date  # noqa: E402


DEFAULT_OUT = Path("data") / "backtest" / "historical_coverage.json"


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


def source_coverage(spec, start_date=None, end_date=None):
    start_year = start_date.year if start_date else None
    end_year = end_date.year if end_date else None
    return {
        "market_id": spec.id,
        "city": spec.city_label,
        "station": spec.icao,
        "unit": spec.display_unit,
        "sources": {
            "wu": history_coverage(wu_store(spec), start_date, end_date),
            "ghcnh": GHCNHStore(spec).coverage(start_year, end_year),
            "reanalysis": ReanalysisStore(spec).coverage(start_date, end_date),
        },
    }


def fleet_coverage(market_ids=None, start_date=None, end_date=None):
    ids = set(market_ids or [])
    specs = [spec for spec in all_specs() if not ids or spec.id in ids]
    return {
        "schema_version": "historical_coverage_v1",
        "markets": [source_coverage(spec, start_date, end_date) for spec in specs],
    }


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
    for market in payload["markets"]:
        bits = []
        for source, coverage in market["sources"].items():
            missing = coverage.get("missing_days", coverage.get("missing_years", []))
            if isinstance(missing, list):
                missing_text = str(len(missing))
            else:
                missing_text = str(missing)
            bits.append(f"{source}:missing={missing_text}")
        print(f"{market['market_id']}: " + ", ".join(bits))


def build_parser():
    parser = argparse.ArgumentParser(description="Report historical-source coverage across markets.")
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report")
    report.add_argument("--markets", default="")
    report.add_argument("--start", default="")
    report.add_argument("--end", default="")
    report.add_argument("--out", default=str(DEFAULT_OUT))
    report.set_defaults(func=cmd_report)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
