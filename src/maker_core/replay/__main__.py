"""Bounded diagnostic CLI. Scored reads remain unavailable in this increment."""
import argparse
from pathlib import Path
import time

from maker_core.replay.bundle import BundleError, Limits, load_bundle
from maker_core.replay.diagnostics import MAX_REPORT_BYTES, coverage_report, write_report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="validate one closed UTC day and report capture coverage")
    run.add_argument("--bundle", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True, help="new directory under an existing parent")
    run.add_argument("--policy", choices=("no_quote", "blind_re1", "clock_only", "informed-v0"),
                     default="no_quote", help="recorded only; diagnostic mode executes no policy")
    mode = run.add_mutually_exclusive_group()
    mode.add_argument("--diagnostic-only", dest="diagnostic_only", action="store_true", default=True)
    mode.add_argument("--compare", dest="diagnostic_only", action="store_false")
    run.add_argument("--pre-registration", type=Path)
    run.add_argument("--pre-registration-sha256")
    run.add_argument("--max-input-bytes", type=int, default=64 * 1024**2)
    run.add_argument("--max-output-bytes", type=int, default=MAX_REPORT_BYTES)
    run.add_argument("--max-records", type=int, default=100_000)
    run.add_argument("--max-seconds", type=float, default=300.0)
    args = parser.parse_args(argv)
    # Gate before any bundle/output/registration IO. An arbitrary hash or a
    # synthetic label is never an owner signature. No allow path exists yet.
    if not args.diagnostic_only or args.pre_registration or args.pre_registration_sha256:
        parser.error("policy comparison is unavailable: owner-signed pre-registration verification "
                     "and scoring are pending; use diagnostic-only without registration flags")
    started = time.monotonic()

    def check():
        if time.monotonic() - started >= args.max_seconds:
            raise BundleError("time_cap")

    try:
        bundle = load_bundle(args.bundle, limits=Limits(args.max_input_bytes, args.max_records, args.max_seconds))
        report = coverage_report(bundle, args.policy, check=check)
        write_report(args.out, report, input_directory=args.bundle,
                     max_bytes=args.max_output_bytes, check=check)
    except (BundleError, OSError) as exc:
        parser.exit(2, f"replay refused: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
