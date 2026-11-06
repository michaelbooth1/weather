"""Independent public pilot evidence CLI. Never loads an account credential.

Owner: INTERNATIONAL_MM_LIVE_PILOT.md, independent public evidence section.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import time
from datetime import date, datetime, timezone

from weather.market.market_registry import BUILTIN_SPECS
from weather.market.pilot_evidence_account import account_flow
from weather.market.pilot_evidence_capture import PublicCapture
from weather.market.pilot_evidence_public import PublicHTTP, RateGate
from weather.market.pilot_evidence_store import CaptureStopped, EvidenceStore, stamp


def utc(text):
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset().total_seconds() != 0:
        raise argparse.ArgumentTypeError("an explicit UTC timestamp is required")
    return value.astimezone(timezone.utc)


def positive(text):
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("a positive finite value is required")
    return value


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("public-capture", help="capture all bands and both public tokens")
    capture.add_argument("--market", action="append", choices=[s.id for s in BUILTIN_SPECS], required=True)
    capture.add_argument("--event-date", type=date.fromisoformat, action="append", required=True)
    for flag in ("all-bands", "both-tokens", "raw-market-stream"):
        capture.add_argument("--" + flag, action="store_true", required=True)
    capture.add_argument("--start-utc", type=utc, required=True)
    capture.add_argument("--end-utc", type=utc, required=True)
    for flag, default in (("rest-book-seconds", 5), ("terms-seconds", 15), ("metadata-seconds", 60),
                          ("time-sample-seconds", 60), ("max-age-seconds", 30), ("max-mark-delay-seconds", 30)):
        capture.add_argument("--" + flag, type=positive, default=default)
    account = commands.add_parser("account-flow", help="export public activity, trades and every position status")
    account.add_argument("--wallet", required=True, help="public 0x wallet/funder address")
    account.add_argument("--from-utc", type=utc, default=datetime.fromtimestamp(1, timezone.utc))
    account.add_argument("--through-utc", type=utc)
    account.add_argument("--page-size", type=int, default=500, choices=range(1, 1001), metavar="1..1000")
    account.add_argument("--max-pages", type=int, default=4096)
    for command in (capture, account):
        command.add_argument("--output", type=Path, required=True, help="new absolute output directory")
        command.add_argument("--max-rest-rps", type=positive, default=2)
        command.add_argument("--max-rss-mib", type=positive, default=256)
        command.add_argument("--max-output-mib", type=positive, default=1536)
    return result


def source_hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(__file__).parent.glob("pilot_evidence_*.py"))} | {
                Path(__file__).name: hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if args.max_rest_rps > 2 or args.max_rss_mib > 256 or not 1 <= args.max_output_mib <= 1536:
        cli.error("hard limits: <=2 REST rps, <=256 MiB RSS, 1..1536 MiB output")
    if not args.output.is_absolute():
        cli.error("output must be absolute")
    if args.command == "public-capture":
        if args.end_utc <= args.start_utc or args.end_utc <= datetime.now(timezone.utc):
            cli.error("end must follow start and be in the future")
    elif (not re.fullmatch(r"0x[0-9a-fA-F]{40}", args.wallet) or args.max_pages < 1 or
          (args.through_utc and args.through_utc <= args.from_utc)):
        cli.error("valid wallet, page cap and increasing time bounds required")
    store = EvidenceStore(args.output, max_output_mib=args.max_output_mib, max_rss_mib=args.max_rss_mib)
    previous = {}

    def interrupted(signum, frame):
        store.fail("operator_stop", signal=signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, interrupted)
    reason = "failed"
    try:
        store.start({"command": args.command, "arguments": {k: str(v) for k, v in vars(args).items()},
                     "source_sha256": source_hashes(), "public_only": True,
                     "pid": os.getpid(),
                     "native_execution_identity_proven": False, "native_sequence_proven": False})
        store.check()
        gate = RateGate(args.max_rest_rps, check=store.check, sleep=store.stop.wait)
        http = PublicHTTP(store, gate)
        if args.command == "public-capture":
            store.end_utc = args.end_utc
            while datetime.now(timezone.utc) < args.start_utc:
                store.check()
                store.stop.wait(min(1, (args.start_utc - datetime.now(timezone.utc)).total_seconds()))
                if time.monotonic() - store.last_health > 30:
                    store.health()
                    store.last_health = time.monotonic()
            late = (datetime.now(timezone.utc) - args.start_utc).total_seconds()
            if late > 1:
                store.gap("late_start", seconds=late)
            PublicCapture(args, store, http).run()
        else:
            through = args.through_utc or datetime.now(timezone.utc)
            store.write("account_cutoff", {"through_utc": through.isoformat(), **stamp()})
            reason = account_flow(args, store, http, int(through.timestamp()))
    except CaptureStopped as exc:
        reason = str(exc)
    except Exception as exc:
        store.fail("unhandled_error", error=type(exc).__name__)
    finally:
        receipt = store.close(reason)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["stop_reason"] in ("end_utc", "account_export_complete") else 1


if __name__ == "__main__":
    raise SystemExit(main())
