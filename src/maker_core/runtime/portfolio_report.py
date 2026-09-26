"""Explicit-path orchestration; accounting itself stays in pure portfolio code."""
import argparse
import json
from pathlib import Path

from maker_core.contracts.portfolio import instant, validate_campaigns
from maker_core.portfolio.ledger import build_book
from maker_core.portfolio.journal import append_book
from maker_core.evidence.journal import canonical_bytes, digest
from maker_core.runtime.portfolio_io import read_json
from maker_core.venue.account_read import adapt_archive


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report")
    report.add_argument("--snapshots", required=True, type=Path)
    report.add_argument("--campaigns", required=True, type=Path)
    report.add_argument("--out", required=True, type=Path)
    report.add_argument("--reader-url")
    report.add_argument("--client-config", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.out.resolve().is_relative_to(args.snapshots.resolve()):
            raise ValueError("journal_must_be_outside_snapshots")
        config = validate_campaigns(read_json(args.campaigns))
        if not args.snapshots.is_dir() or args.snapshots.is_symlink():
            raise ValueError("snapshot_directory_required")
        snapshots = [adapt_archive(read_json(path)) for path in sorted(args.snapshots.glob("*.json"))]
        if bool(args.reader_url) != bool(args.client_config):
            raise ValueError("reader_url_and_client_config_required")
        if args.reader_url:
            from maker_core.runtime.credentials import reader_credentials
            from maker_core.venue.portfolio_client import read_archive
            since = int(min(instant(c["start_utc"]) for c in config["campaigns"]).timestamp())
            captured = adapt_archive(read_archive(args.reader_url, reader_credentials(args.client_config), since))
            archive = args.snapshots / (digest(captured) + ".json")
            with archive.open("xb") as handle:
                handle.write(canonical_bytes(captured))
            snapshots.append(captured)
        book = build_book(snapshots, config)
        receipt = append_book(args.out, book)
        print(json.dumps(dict(status=book["status"], reasons=book["reasons"], **receipt)))
        return 0 if book["status"] == "OBSERVED" else 2
    except (ValueError, OSError, KeyError, TypeError):
        print(json.dumps({"error": "portfolio_report_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
