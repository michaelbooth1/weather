"""Registry-driven historical-source backfill helper.

Defaults are deliberately resumable: existing raw payloads are skipped and the
normalized hourly/daily artifacts are rebuilt after each market/source.
"""
import argparse
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from market_registry import all_specs  # noqa: E402


DEFAULT_START = "2015-01-01"
DEFAULT_END = date.today().isoformat()
DEFAULT_MARKETS = [spec.id for spec in all_specs()]
DEFAULT_SOURCES = ("wu", "ghcnh", "reanalysis")


def year_from_date(value):
    return datetime.fromisoformat(str(value)).date().year


def build_wu_command(python, market, start, end, chunk_days, sleep, skip_existing):
    command = [
        str(python),
        "-m",
        "src.wu_history",
        "--market",
        market,
        "backfill",
        "--start",
        start,
        "--end",
        end,
        "--chunk-days",
        str(chunk_days),
        "--sleep",
        str(sleep),
    ]
    if skip_existing:
        command.append("--skip-existing")
    command.append("--continue-on-error")
    return command


def build_ghcnh_command(python, market, start, end, sleep, skip_existing):
    command = [
        str(python),
        "-m",
        "src.noaa_ghcnh_history",
        "--market",
        market,
        "backfill",
        "--start-year",
        str(year_from_date(start)),
        "--end-year",
        str(year_from_date(end)),
        "--sleep",
        str(sleep),
    ]
    if skip_existing:
        command.append("--skip-existing")
    return command


def build_reanalysis_command(python, market, start, end, chunk_days, sleep, skip_existing):
    command = [
        str(python),
        "-m",
        "src.reanalysis_history",
        "--market",
        market,
        "backfill",
        "--start",
        start,
        "--end",
        end,
        "--chunk-days",
        str(chunk_days),
        "--sleep",
        str(sleep),
    ]
    if skip_existing:
        command.append("--skip-existing")
    return command


def build_command(source, python, market, start, end, chunk_days, sleep, skip_existing):
    if source == "wu":
        return build_wu_command(python, market, start, end, chunk_days, sleep, skip_existing)
    if source == "ghcnh":
        return build_ghcnh_command(python, market, start, end, sleep, skip_existing)
    if source == "reanalysis":
        return build_reanalysis_command(python, market, start, end, chunk_days, sleep, skip_existing)
    raise ValueError(f"unknown source: {source}")


def parse_args():
    parser = argparse.ArgumentParser(description="Backfill historical sources for registered markets.")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--markets", default=",".join(DEFAULT_MARKETS), help="Comma-separated market ids.")
    parser.add_argument("--sources", default=",".join(DEFAULT_SOURCES), help="Comma-separated: wu,ghcnh,reanalysis.")
    parser.add_argument("--chunk-days", type=int, default=14)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--between-markets-sleep", type=float, default=1.0)
    parser.add_argument("--python", default=str(Path("venv") / "Scripts" / "python.exe"))
    parser.add_argument("--refetch-existing", action="store_true", help="Fetch all chunks instead of skipping raw days.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    markets = [item.strip() for item in args.markets.split(",") if item.strip()]
    sources = [item.strip() for item in args.sources.split(",") if item.strip()]
    for market in markets:
        for source in sources:
            command = build_command(
                source,
                args.python,
                market,
                args.start,
                args.end,
                args.chunk_days,
                args.sleep,
                skip_existing=not args.refetch_existing,
            )
            print(f"Backfilling {market}/{source}: {' '.join(command)}")
            if args.dry_run:
                continue
            subprocess.run(command, check=True)
        if args.between_markets_sleep:
            time.sleep(args.between_markets_sleep)
    print("All requested market backfills completed.")


if __name__ == "__main__":
    main()
