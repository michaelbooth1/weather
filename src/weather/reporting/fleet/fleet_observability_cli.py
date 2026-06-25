"""Implementation slice extracted from src/weather/reporting/fleet/fleet_observability.py."""

from weather.reporting.fleet.fleet_observability_render import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def cmd_report(args):
    years = [int(item) for item in args.years.split(",") if item.strip()] if args.years else None
    payload = build_observability_payload(
        snapshots_root=Path(args.snapshots_root),
        interval_minutes=args.interval_minutes,
        tolerance=args.tolerance,
        target_month=args.target_month,
        target_day=args.target_day,
        years=years,
        include_audits=not args.skip_audits,
        tape_backup_root=args.tape_backup_root,
        tape_backup_status_path=args.tape_backup_status,
        refresh_tape_backup_status=args.refresh_tape_backup_status,
        verify_tape_backup_checksums=args.verify_tape_backup_checksums,
    )
    json_path = write_json(args.out, payload)
    report_path = write_markdown(args.report, payload)
    provenance_path = write_json(args.provenance_out, payload["artifact_provenance"])
    print(f"Fleet observability: {payload['status']}")
    print(f"Wrote JSON to {json_path}")
    print(f"Wrote report to {report_path}")
    print(f"Wrote artifact provenance manifest to {provenance_path}")
    if args.strict and payload["status"] == "CRITICAL":
        sys.exit(2)


def build_parser():
    parser = argparse.ArgumentParser(description="Build fleet data-integrity and observability reports.")
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report")
    report.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    report.add_argument("--interval-minutes", type=float, default=10.0)
    report.add_argument("--tolerance", type=float, default=1.5)
    report.add_argument("--target-month", type=int, default=None)
    report.add_argument("--target-day", type=int, default=None)
    report.add_argument("--years", default="", help="Comma-separated audit years; default 2000-2025.")
    report.add_argument("--skip-audits", action="store_true")
    report.add_argument("--tape-backup-root", default=str(tape_backup.DEFAULT_BACKUP_ROOT))
    report.add_argument("--tape-backup-status", default=str(tape_backup.DEFAULT_STATUS_OUT))
    report.add_argument(
        "--refresh-tape-backup-status",
        action="store_true",
        help="Recompute the full tape-backup status instead of reading the generated status artifact.",
    )
    report.add_argument("--verify-tape-backup-checksums", action="store_true")
    report.add_argument("--strict", action="store_true", help="Exit 2 when critical alerts are present.")
    report.add_argument("--out", default=str(DEFAULT_JSON_OUT))
    report.add_argument("--report", default=str(DEFAULT_REPORT))
    report.add_argument("--provenance-out", default=str(DEFAULT_PROVENANCE_OUT))
    report.set_defaults(func=cmd_report)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
