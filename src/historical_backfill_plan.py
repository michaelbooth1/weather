"""Build and optionally run the item-29 historical backfill queue.

This is the bridge between "adapters exist" and "the training window is fully
populated." It inspects local raw coverage and writes concrete resumable queue
items for WU, NOAA GHCNh, and ERA5-style reanalysis.
"""
import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_registry import all_specs, spec_for_id  # noqa: E402
from noaa_ghcnh_history import GHCNHStore  # noqa: E402
from reanalysis_history import ReanalysisStore  # noqa: E402
from wu_history import WundergroundHistoryStore, parse_date  # noqa: E402


DEFAULT_OUT = Path("data") / "backtest" / "historical_backfill_plan.json"
DEFAULT_MINIMUM_START = date(2015, 1, 1)
DEFAULT_DEEP_START = date(1940, 1, 1)
DEFAULT_WU_CHUNK_DAYS = 14
DEFAULT_REANALYSIS_CHUNK_DAYS = 31
DEFAULT_SOURCES = ("wu", "ghcnh", "reanalysis")


def iter_dates(start_date, end_date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def split_ranges(missing_dates, chunk_days):
    missing_dates = sorted(set(missing_dates))
    if not missing_dates:
        return []
    ranges = []
    run_start = prev = missing_dates[0]
    for current in missing_dates[1:]:
        if current == prev + timedelta(days=1):
            prev = current
            continue
        ranges.extend(chunk_range(run_start, prev, chunk_days))
        run_start = prev = current
    ranges.extend(chunk_range(run_start, prev, chunk_days))
    return ranges


def chunk_range(start_date, end_date, chunk_days):
    current = start_date
    ranges = []
    while current <= end_date:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end_date)
        ranges.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return ranges


def spec_list(market_ids=None):
    ids = [item.strip() for item in (market_ids or []) if item.strip()]
    if not ids:
        return all_specs()
    return [spec_for_id(market_id) for market_id in ids]


def python_path(default=None):
    return default or str(Path("venv") / "Scripts" / "python.exe")


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


def queue_item(source, spec, command, detail):
    return {
        "source": source,
        "market_id": spec.id,
        "station": spec.icao,
        "unit": spec.display_unit,
        "command": command,
        "detail": detail,
    }


def wu_queue(spec, start_date, end_date, python, chunk_days):
    items = []
    for start, end in wu_store(spec).missing_ranges(start_date, end_date, chunk_days=chunk_days):
        items.append(queue_item(
            "wu",
            spec,
            [
                python,
                "-m",
                "src.wu_history",
                "--market",
                spec.id,
                "backfill",
                "--start",
                start.isoformat(),
                "--end",
                end.isoformat(),
                "--chunk-days",
                str(chunk_days),
                "--skip-existing",
                "--continue-on-error",
            ],
            {"start": start.isoformat(), "end": end.isoformat(), "kind": "date_range"},
        ))
    return items


def ghcnh_queue(spec, start_date, end_date, python):
    store = GHCNHStore(spec)
    items = []
    if not store.read_station():
        items.append(queue_item(
            "ghcnh",
            spec,
            [python, "-m", "src.noaa_ghcnh_history", "--market", spec.id, "station"],
            {"kind": "station_resolution"},
        ))
    for year in store.missing_years(start_date.year, end_date.year):
        items.append(queue_item(
            "ghcnh",
            spec,
            [
                python,
                "-m",
                "src.noaa_ghcnh_history",
                "--market",
                spec.id,
                "backfill",
                "--start-year",
                str(year),
                "--end-year",
                str(year),
                "--skip-existing",
            ],
            {"year": year, "kind": "year"},
        ))
    return items


def reanalysis_queue(spec, start_date, end_date, python, chunk_days):
    store = ReanalysisStore(spec)
    items = []
    for start, end in store.missing_ranges(start_date, end_date, chunk_days=chunk_days):
        items.append(queue_item(
            "reanalysis",
            spec,
            [
                python,
                "-m",
                "src.reanalysis_history",
                "--market",
                spec.id,
                "backfill",
                "--start",
                start.isoformat(),
                "--end",
                end.isoformat(),
                "--chunk-days",
                str(chunk_days),
                "--skip-existing",
            ],
            {"start": start.isoformat(), "end": end.isoformat(), "kind": "date_range"},
        ))
    return items


def queue_for_source(source, spec, start_date, end_date, python, wu_chunk_days, reanalysis_chunk_days):
    if source == "wu":
        return wu_queue(spec, start_date, end_date, python, wu_chunk_days)
    if source == "ghcnh":
        return ghcnh_queue(spec, start_date, end_date, python)
    if source == "reanalysis":
        return reanalysis_queue(spec, start_date, end_date, python, reanalysis_chunk_days)
    raise ValueError(f"unknown historical source: {source}")


def build_plan(
    market_ids=None,
    sources=DEFAULT_SOURCES,
    start_date=DEFAULT_MINIMUM_START,
    end_date=None,
    scope="minimum",
    python=None,
    wu_chunk_days=DEFAULT_WU_CHUNK_DAYS,
    reanalysis_chunk_days=DEFAULT_REANALYSIS_CHUNK_DAYS,
):
    end_date = end_date or date.today()
    if scope == "deep" and start_date == DEFAULT_MINIMUM_START:
        start_date = DEFAULT_DEEP_START
    py = python_path(python)
    items = []
    for spec in spec_list(market_ids):
        for source in sources:
            items.extend(queue_for_source(
                source,
                spec,
                start_date,
                end_date,
                py,
                wu_chunk_days,
                reanalysis_chunk_days,
            ))
    counts = {}
    for item in items:
        key = item["source"]
        counts[key] = counts.get(key, 0) + 1
    return {
        "schema_version": "historical_backfill_plan_v1",
        "scope": scope,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "sources": list(sources),
        "market_count": len(spec_list(market_ids)),
        "queue_count": len(items),
        "queue_count_by_source": counts,
        "queue": items,
    }


def write_plan(plan, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_queue_items(items, dry_run=True):
    for item in items:
        print(f"{item['market_id']}/{item['source']}: {' '.join(item['command'])}")
        if not dry_run:
            subprocess.run(item["command"], check=True)


def parse_csv(value):
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def cmd_plan(args):
    plan = build_plan(
        market_ids=parse_csv(args.markets),
        sources=parse_csv(args.sources) or list(DEFAULT_SOURCES),
        start_date=parse_date(args.start),
        end_date=parse_date(args.end),
        scope=args.scope,
        python=args.python,
        wu_chunk_days=args.wu_chunk_days,
        reanalysis_chunk_days=args.reanalysis_chunk_days,
    )
    write_plan(plan, args.out)
    print(f"Wrote historical backfill plan to {args.out}")
    print(f"Queue items: {plan['queue_count']} ({plan['queue_count_by_source']})")
    selected = plan["queue"][:args.limit_items] if args.limit_items else []
    if selected:
        run_queue_items(selected, dry_run=args.dry_run)


def build_parser():
    parser = argparse.ArgumentParser(description="Build and optionally run historical backfill queue.")
    parser.add_argument("--markets", default="")
    parser.add_argument("--sources", default=",".join(DEFAULT_SOURCES))
    parser.add_argument("--start", default=DEFAULT_MINIMUM_START.isoformat())
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--scope", choices=("minimum", "deep"), default="minimum")
    parser.add_argument("--python", default=python_path())
    parser.add_argument("--wu-chunk-days", type=int, default=DEFAULT_WU_CHUNK_DAYS)
    parser.add_argument("--reanalysis-chunk-days", type=int, default=DEFAULT_REANALYSIS_CHUNK_DAYS)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--limit-items", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.set_defaults(func=cmd_plan)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
