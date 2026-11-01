"""WU history vs the venue METAR rule, per built-in US market (read-only research).

Answers one question for the post-10-23 label decision: on dates before the
venue switch, how often does the configured WU daily high agree with the venue
rule (highest ROUTINE METAR, SPECI excluded, T-group tenths of a degree C,
half-up to the native unit) at the same WU station?

Two subcommands, run serially:

  fetch    downloads routine-only IEM METAR (network) into --metar-root
  compare  reads those files plus the market's WU daily summary (read-only)
           and writes one JSON result and prints a table

Nothing is written under data/ unless --metar-root or --out point there. The
WU daily summary is only read. Dates are bounded by --start/--end and refused
after 2026-09-29.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from weather.backtesting.settlement_ledger import daily_summary_path_for_spec
from weather.backtesting.venue_rule_labels import (
    VENUE_RULE_VERSION,
    fetch_routine,
    read_wu_rows,
    reports_from_csv,
    routine_csv_files,
    venue_daily_labels,
    wu_station_icao,
)
from weather.market.market_registry import BUILTIN_SPECS
from weather.paths import data_path
from weather.sources.daily_summary import native_bucket
from weather.sources.metar_history import IEM_REPORT_TYPE_ROUTINE

LAST_ALLOWED = date(2026, 9, 29)
BAND_WIDTH = 2  # Even-start 2-degree interior bands, as in the 10-23 studies.


def us_specs(markets=None):
    specs = [spec for spec in BUILTIN_SPECS if spec.display_unit.upper().startswith("F")]
    if markets:
        wanted = set(markets)
        specs = [spec for spec in specs if spec.id in wanted]
    return specs


def _dates(start, end):
    if end > LAST_ALLOWED:
        raise SystemExit(f"--end {end} is after {LAST_ALLOWED}; refused")
    if start > end:
        raise SystemExit("--start is after --end")
    return start, end


def cmd_fetch(args):
    start, end = _dates(date.fromisoformat(args.start), date.fromisoformat(args.end))
    # One extra UTC day either side so every local date is whole.
    for spec in us_specs(args.markets):
        icao = wu_station_icao(spec)
        path = fetch_routine(icao, start - timedelta(days=1), end + timedelta(days=1), metar_root=args.metar_root)
        print(f"fetched {spec.id} {icao} -> {path}", flush=True)
        time.sleep(args.pause_seconds)
    return 0


def wu_summary_path(spec, wu_data_root=None):
    """The market's WU daily summary, optionally re-rooted onto another checkout's data/."""

    path = daily_summary_path_for_spec(spec)
    if wu_data_root is None:
        return path
    return Path(wu_data_root) / path.relative_to(data_path())


def compare_market(spec, metar_root, start, end, wu_data_root=None):
    icao = wu_station_icao(spec)
    reports = []
    for path in routine_csv_files(metar_root, icao):
        reports.extend(reports_from_csv(
            path.read_text(encoding="utf-8"), spec, icao, declared_report_type=IEM_REPORT_TYPE_ROUTINE,
        ))
    reports.sort(key=lambda item: item["valid_time_utc"])
    venue = venue_daily_labels(reports, spec)
    wu_path = wu_summary_path(spec, wu_data_root)
    if not wu_path.exists():
        raise SystemExit(f"{spec.id}: WU daily summary not found at {wu_path}")
    wu = read_wu_rows(wu_path)
    diffs, flips, compared, missing_wu, missing_venue = Counter(), 0, 0, [], []
    day = start
    while day <= end:
        key = day.isoformat()
        wu_row, venue_row = wu.get(key), venue.get(key)
        if wu_row is None:
            missing_wu.append(key)
        elif venue_row is None:
            missing_venue.append(key)
        else:
            w, v = native_bucket(wu_row), native_bucket(venue_row)
            if w is None or v is None:
                missing_venue.append(key)
            else:
                compared += 1
                diffs[int(v) - int(w)] += 1
                flips += int(int(v) // BAND_WIDTH != int(w) // BAND_WIDTH)
        day += timedelta(days=1)
    exact = diffs.get(0, 0)
    return {
        "market": spec.id,
        "wu_daily_summary": str(wu_path),
        "station": icao,
        "compared_days": compared,
        "exact_match": exact,
        "exact_match_rate": round(exact / compared, 4) if compared else None,
        "difference_counts_venue_minus_wu": {str(k): diffs[k] for k in sorted(diffs)},
        "band_flips_2deg_even_start": flips,
        "missing_wu_dates": missing_wu,
        "missing_venue_dates": missing_venue,
    }


def cmd_compare(args):
    start, end = _dates(date.fromisoformat(args.start), date.fromisoformat(args.end))
    rows = [compare_market(spec, args.metar_root, start, end, args.wu_data_root) for spec in us_specs(args.markets)]
    total = sum(row["compared_days"] for row in rows)
    exact = sum(row["exact_match"] for row in rows)
    flips = sum(row["band_flips_2deg_even_start"] for row in rows)
    result = {
        "schema": "wu-vs-venue-measure",
        "rule_version": VENUE_RULE_VERSION,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "band_width": BAND_WIDTH,
        "markets": rows,
        "total": {"compared_days": total, "exact_match": exact, "band_flips_2deg_even_start": flips},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{'market':<15}{'station':<8}{'n':>5}{'exact':>7}{'flips':>7}  diffs(venue-wu)")
    for row in rows:
        print(f"{row['market']:<15}{row['station']:<8}{row['compared_days']:>5}{row['exact_match']:>7}"
              f"{row['band_flips_2deg_even_start']:>7}  {row['difference_counts_venue_minus_wu']}")
    print(f"{'TOTAL':<23}{total:>5}{exact:>7}{flips:>7}")
    print(f"wrote {out}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("fetch", "compare"):
        p = sub.add_parser(name)
        p.add_argument("--metar-root", required=True, help="Scratch directory for routine METAR CSVs.")
        p.add_argument("--start", default="2026-08-11")
        p.add_argument("--end", default="2026-09-29")
        p.add_argument("--markets", nargs="*", help="Built-in market ids (default: the US 11).")
        if name == "fetch":
            p.add_argument("--pause-seconds", type=float, default=5.0)
        else:
            p.add_argument("--out", required=True, help="Result JSON path (scratch).")
            p.add_argument("--wu-data-root", help="Read WU daily summaries from this data/ directory (read-only).")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return cmd_fetch(args) if args.command == "fetch" else cmd_compare(args)


if __name__ == "__main__":
    sys.exit(main())
