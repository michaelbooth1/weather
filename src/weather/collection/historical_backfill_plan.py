"""Build and optionally run the item-29 historical backfill queue.

This is the bridge between "adapters exist" and "the training window is fully
populated." It inspects local raw coverage and writes concrete resumable queue
items for WU, NOAA GHCNh, and ERA5-style reanalysis.
"""
import argparse
import json
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

from weather.paths import data_path

from weather.market.market_registry import all_specs, spec_for_id
from weather.sources.noaa_ghcnh_history import GHCNHStore
from weather.sources.reanalysis_history import ReanalysisStore
from weather.sources.wu_history import WundergroundHistoryStore, parse_date


DEFAULT_OUT = data_path() / "backtest" / "historical_backfill_plan.json"
DEFAULT_MINIMUM_START = date(2015, 1, 1)
DEFAULT_DEEP_START = date(1940, 1, 1)
DEFAULT_WU_CHUNK_DAYS = 14
DEFAULT_REANALYSIS_CHUNK_DAYS = 31
DEFAULT_SOURCES = ("wu", "ghcnh", "reanalysis")
DEFAULT_QUEUE_MODE = "market_source"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
US_WU_PROVIDER_UNAVAILABLE_BEFORE = date(2015, 1, 1)


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


def source_limited_item(item, reason, evidence_path=None):
    limited = dict(item)
    limited["source_limited"] = True
    limited["reason"] = reason
    if evidence_path:
        limited["evidence_path"] = str(evidence_path)
    return limited


def replace_command_arg(command, flag, value):
    command = list(command or [])
    try:
        index = command.index(flag)
    except ValueError:
        return command
    if index + 1 < len(command):
        command[index + 1] = value
    return command


def latest_us_wu_provider_probe(backtest_root=DEFAULT_BACKTEST_ROOT):
    root = Path(backtest_root)
    probes = sorted(root.glob("source_alternate_probe_*.json"))
    if not probes:
        return {
            "exists": False,
            "path": None,
            "us_market_count": 0,
            "available_candidate_count": 0,
        }
    path = probes[-1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "exists": False,
            "path": str(path),
            "us_market_count": 0,
            "available_candidate_count": 0,
        }
    available = 0
    markets = payload.get("us_wu_candidates") or []
    for market in markets:
        for candidate in market.get("candidates") or []:
            if candidate.get("available"):
                available += 1
    return {
        "exists": True,
        "path": str(path),
        "generated_at_utc": payload.get("generated_at_utc"),
        "us_market_count": len(markets),
        "available_candidate_count": available,
    }


def days_in_ranges(ranges):
    return sum((end - start).days + 1 for start, end in ranges)


def window_from_ranges(ranges):
    if not ranges:
        return None, None
    return min(start for start, _end in ranges), max(end for _start, end in ranges)


def item_window(item):
    detail = item.get("detail") or {}
    start = detail.get("start")
    end = detail.get("end")
    if start and end:
        return parse_date(start), parse_date(end)
    return None, None


def classify_source_limited_items(items, backtest_root=DEFAULT_BACKTEST_ROOT):
    probe = latest_us_wu_provider_probe(backtest_root)
    source_limited = []
    executable = []
    wu_unavailable_reason = (
        "pre-2015 US Weather.com full-history gap is provider-unavailable; "
        "alternate-ID probe found no available ICAO:9:US candidates"
    )
    for item in items:
        start, end = item_window(item)
        is_pre_2015_us_wu = (
            item.get("source") == "wu"
            and item.get("market_id") != "toronto"
            and start is not None
            and end is not None
            and start < US_WU_PROVIDER_UNAVAILABLE_BEFORE
            and probe.get("exists")
            and int(probe.get("available_candidate_count") or 0) == 0
        )
        if is_pre_2015_us_wu:
            limited = source_limited_item(
                item,
                wu_unavailable_reason,
                evidence_path=probe.get("path"),
            )
            limited_detail = dict(limited.get("detail") or {})
            limited_detail["end"] = min(end, US_WU_PROVIDER_UNAVAILABLE_BEFORE - timedelta(days=1)).isoformat()
            limited["detail"] = limited_detail
            source_limited.append(limited)
            if end >= US_WU_PROVIDER_UNAVAILABLE_BEFORE:
                retained = dict(item)
                retained["command"] = replace_command_arg(
                    retained.get("command"),
                    "--start",
                    US_WU_PROVIDER_UNAVAILABLE_BEFORE.isoformat(),
                )
                retained_detail = dict(retained.get("detail") or {})
                retained_detail["start"] = US_WU_PROVIDER_UNAVAILABLE_BEFORE.isoformat()
                retained_detail["source_limited_prefix_removed"] = True
                retained["detail"] = retained_detail
                executable.append(retained)
            continue
        executable.append(item)
    return executable, source_limited, {"us_wu_provider_probe": probe}


def wu_chunk_queue(spec, start_date, end_date, python, chunk_days):
    items = []
    for start, end in wu_store(spec).missing_ranges(start_date, end_date, chunk_days=chunk_days):
        items.append(queue_item(
            "wu",
            spec,
            [
                python,
                "-m",
                "weather.sources.wu_history",
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


def wu_market_source_queue(spec, start_date, end_date, python, chunk_days):
    ranges = wu_store(spec).missing_ranges(start_date, end_date, chunk_days=chunk_days)
    if not ranges:
        return []
    first_missing, last_missing = window_from_ranges(ranges)
    return [queue_item(
        "wu",
        spec,
        [
            python,
            "-m",
            "weather.sources.wu_history",
            "--market",
            spec.id,
            "backfill",
            "--start",
            first_missing.isoformat(),
            "--end",
            last_missing.isoformat(),
            "--chunk-days",
            str(chunk_days),
            "--skip-existing",
            "--continue-on-error",
        ],
        {
            "start": first_missing.isoformat(),
            "end": last_missing.isoformat(),
            "kind": "market_source_date_window",
            "missing_ranges": len(ranges),
            "missing_days": days_in_ranges(ranges),
            "chunk_days": chunk_days,
        },
    )]


def wu_queue(spec, start_date, end_date, python, chunk_days, queue_mode=DEFAULT_QUEUE_MODE):
    if queue_mode == "chunk":
        return wu_chunk_queue(spec, start_date, end_date, python, chunk_days)
    return wu_market_source_queue(spec, start_date, end_date, python, chunk_days)


def ghcnh_chunk_queue(spec, start_date, end_date, python):
    store = GHCNHStore(spec)
    items = []
    if not store.read_station():
        items.append(queue_item(
            "ghcnh",
            spec,
            [python, "-m", "weather.sources.noaa_ghcnh_history", "--market", spec.id, "station"],
            {"kind": "station_resolution"},
        ))
    for year in store.missing_years(start_date.year, end_date.year):
        items.append(queue_item(
            "ghcnh",
            spec,
            [
                python,
                "-m",
                "weather.sources.noaa_ghcnh_history",
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


def ghcnh_market_source_queue(spec, start_date, end_date, python):
    store = GHCNHStore(spec)
    missing_years = store.missing_years(start_date.year, end_date.year)
    if missing_years:
        return [queue_item(
            "ghcnh",
            spec,
            [
                python,
                "-m",
                "weather.sources.noaa_ghcnh_history",
                "--market",
                spec.id,
                "backfill",
                "--start-year",
                str(min(missing_years)),
                "--end-year",
                str(max(missing_years)),
                "--skip-existing",
            ],
            {
                "kind": "market_source_year_window",
                "start_year": min(missing_years),
                "end_year": max(missing_years),
                "missing_years": missing_years,
                "missing_year_count": len(missing_years),
            },
        )]
    if not store.read_station():
        return [queue_item(
            "ghcnh",
            spec,
            [python, "-m", "weather.sources.noaa_ghcnh_history", "--market", spec.id, "station"],
            {"kind": "station_resolution"},
        )]
    return []


def ghcnh_queue(spec, start_date, end_date, python, queue_mode=DEFAULT_QUEUE_MODE):
    if queue_mode == "chunk":
        return ghcnh_chunk_queue(spec, start_date, end_date, python)
    return ghcnh_market_source_queue(spec, start_date, end_date, python)


def reanalysis_chunk_queue(spec, start_date, end_date, python, chunk_days):
    store = ReanalysisStore(spec)
    items = []
    for start, end in store.missing_ranges(start_date, end_date, chunk_days=chunk_days):
        items.append(queue_item(
            "reanalysis",
            spec,
            [
                python,
                "-m",
                "weather.sources.reanalysis_history",
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


def reanalysis_market_source_queue(spec, start_date, end_date, python, chunk_days):
    store = ReanalysisStore(spec)
    ranges = store.missing_ranges(start_date, end_date, chunk_days=chunk_days)
    if not ranges:
        return []
    first_missing, last_missing = window_from_ranges(ranges)
    return [queue_item(
        "reanalysis",
        spec,
        [
            python,
            "-m",
            "weather.sources.reanalysis_history",
            "--market",
            spec.id,
            "backfill",
            "--start",
            first_missing.isoformat(),
            "--end",
            last_missing.isoformat(),
            "--chunk-days",
            str(chunk_days),
            "--skip-existing",
        ],
        {
            "start": first_missing.isoformat(),
            "end": last_missing.isoformat(),
            "kind": "market_source_date_window",
            "missing_ranges": len(ranges),
            "missing_days": days_in_ranges(ranges),
            "chunk_days": chunk_days,
        },
    )]


def reanalysis_queue(spec, start_date, end_date, python, chunk_days, queue_mode=DEFAULT_QUEUE_MODE):
    if queue_mode == "chunk":
        return reanalysis_chunk_queue(spec, start_date, end_date, python, chunk_days)
    return reanalysis_market_source_queue(spec, start_date, end_date, python, chunk_days)


def queue_for_source(source, spec, start_date, end_date, python, wu_chunk_days, reanalysis_chunk_days, queue_mode):
    if source == "wu":
        return wu_queue(spec, start_date, end_date, python, wu_chunk_days, queue_mode)
    if source == "ghcnh":
        return ghcnh_queue(spec, start_date, end_date, python, queue_mode)
    if source == "reanalysis":
        return reanalysis_queue(spec, start_date, end_date, python, reanalysis_chunk_days, queue_mode)
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
    queue_mode=DEFAULT_QUEUE_MODE,
    backtest_root=DEFAULT_BACKTEST_ROOT,
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
                queue_mode,
            ))
    items, source_limited, policy = classify_source_limited_items(items, backtest_root=backtest_root)
    counts = {}
    for item in items:
        key = item["source"]
        counts[key] = counts.get(key, 0) + 1
    limited_counts = {}
    for item in source_limited:
        key = item["source"]
        limited_counts[key] = limited_counts.get(key, 0) + 1
    return {
        "schema_version": "historical_backfill_plan_v1",
        "scope": scope,
        "queue_mode": queue_mode,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "sources": list(sources),
        "market_count": len(spec_list(market_ids)),
        "queue_count": len(items),
        "queue_count_by_source": counts,
        "source_limited_count": len(source_limited),
        "source_limited_count_by_source": limited_counts,
        "source_limited_policy": policy,
        "source_limited": source_limited,
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
        queue_mode=args.queue_mode,
        backtest_root=args.backtest_root,
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
    parser.add_argument("--queue-mode", choices=("market_source", "chunk"), default=DEFAULT_QUEUE_MODE)
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
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
