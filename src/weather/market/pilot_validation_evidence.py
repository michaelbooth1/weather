"""Supervised, public-only pilot capture, readiness and account-flow CLI."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import time

from weather.paths import PACKAGE_ROOT, REPO_ROOT
from weather.market.pilot_evidence_account import account_flow
from weather.market.pilot_evidence_capture import PublicCapture, readiness_from_capture
from weather.market.pilot_evidence_contract import BUILTIN_SPECS, ClockPlan, F0_COMMIT
from weather.market.pilot_evidence_public import PublicHTTP, RateGate
from weather.market.pilot_evidence_store import CaptureStopped, EvidenceStore
from weather.market.pilot_evidence_supervisor import WorkerLifeline, supervise


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
    capture = commands.add_parser("public-capture")
    launch = commands.add_parser("launch", help="start only the independent evidence process; no wait/restart")
    launch.add_argument("--expected-tip", required=True)
    stop = commands.add_parser("stop", help="request STOP through the evidence process's own handle")
    stop.add_argument("--output", type=Path, required=True)
    for command in (capture, launch):
        command.add_argument("--market", action="append", choices=[s.id for s in BUILTIN_SPECS], required=True)
        command.add_argument("--event-date", type=date.fromisoformat, action="append", required=True)
        for flag in ("all-bands", "both-tokens", "raw-market-stream"):
            command.add_argument("--" + flag, action="store_true", required=True)
        command.add_argument("--start-utc", type=utc, help="optional planned start; omitted means start now")
        command.add_argument("--end-utc", type=utc, required=True)
    readiness = commands.add_parser("readiness", help="compare all four F0 pre-filter events and validate every baseline")
    readiness.add_argument("--session-date", type=date.fromisoformat, default=date(2026, 11, 9))
    readiness.add_argument("--capture-health", type=Path, help="verify active capture without a second REST budget")
    readiness.add_argument("--pre-start", action="store_true", help="assert this public walk precedes the independent collector launch")
    readiness.add_argument("--end-utc", type=utc, required=True, help="same absolute end as the capture launch")
    for command in (capture, launch, readiness):
        for flag, default in (("rest-book-seconds", 5), ("terms-seconds", 60), ("fee-seconds", 180),
                              ("fee-rate-seconds", 180), ("metadata-seconds", 180), ("time-sample-seconds", 60),
                              ("max-age-seconds", 30), ("max-mark-delay-seconds", 30)):
            command.add_argument("--" + flag, type=positive, default=default)
    account = commands.add_parser("account-flow")
    account.add_argument("--wallet", required=True, help="public 0x funder address")
    account.add_argument("--from-utc", type=utc, default=datetime.fromtimestamp(1, timezone.utc))
    account.add_argument("--through-utc", type=utc)
    account.add_argument("--page-size", type=int, default=500, choices=range(1, 1001), metavar="1..1000")
    account.add_argument("--max-pages", type=int, default=4096)
    for command in (capture, launch, readiness, account):
        command.add_argument("--output", type=Path, required=True, help="new absolute task/pilot evidence directory")
        command.add_argument("--max-rest-rps", type=positive, default=2)
        command.add_argument("--max-rss-mib", type=positive, default=256)
        command.add_argument("--max-output-mib", type=positive, default=4096)
        command.add_argument("--min-free-gib", type=positive, default=40)
    return result


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def source_hashes():
    return {p.name: file_hash(p) for p in sorted(Path(__file__).parent.glob("pilot_evidence_*.py"))} | {
        Path(__file__).name: file_hash(Path(__file__))}


def runtime_pin():
    paths = {str(Path(module.__file__).resolve()) for module in tuple(sys.modules.values())
             if getattr(module, "__file__", None) and Path(module.__file__).is_file()}
    paths.update(str(Path(module.__cached__).resolve()) for module in tuple(sys.modules.values())
                 if getattr(module, "__cached__", None) and Path(module.__cached__).is_file())
    paths.update(str(p) for p in (Path(sys.executable), Path(sys._base_executable),
                 PACKAGE_ROOT / "market" / "market_registry.py", REPO_ROOT / "sitecustomize.py",
                 REPO_ROOT / "weather" / "__init__.py", REPO_ROOT / "pyproject.toml",
                 REPO_ROOT / "requirements.txt") if p.is_file())
    if os.name == "nt":
        dll = Path(sys.base_prefix) / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
        if dll.is_file():
            paths.add(str(dll))
        paths.update(str(path) for path in (Path(sys.base_prefix) / "DLLs").glob("*.dll") if path.is_file())
    return {"python": sys.version, "executable": sys.executable, "base_executable": sys._base_executable,
            "files_sha256": {path: file_hash(Path(path)) for path in sorted(paths)},
            "module_origins": {name: getattr(getattr(module, "__spec__", None), "origin", None)
                               for name, module in tuple(sys.modules.items())},
            "windows_version": tuple(sys.getwindowsversion()) if os.name == "nt" else None,
            "ambient_policy": "no registry import/override read; direct TLS ignores proxy/netrc/cookies",
            "websocket_implementation": "bounded RFC6455 transport in pilot_evidence_transport; no library receiver"}


def worker_main(args, channel, cancel):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    lifeline = WorkerLifeline(args.output, channel, cancel)
    store = EvidenceStore(args.output, max_output_mib=args.max_output_mib, max_rss_mib=args.max_rss_mib,
                          min_free_gib=args.min_free_gib, existing_root=True,
                          health_sink=lifeline.publish, cancel=cancel)
    reason = "failed"
    joined = True
    try:
        plan = ClockPlan(start=getattr(args, "start_utc", None), end=getattr(args, "end_utc", None))
        store.plan = plan
        store.start({"command": args.command, "arguments": {k: str(v) for k, v in vars(args).items()},
                     "source_sha256": source_hashes(), "runtime_pin": runtime_pin(),
                     "clock_anchors": plan.anchors(), "public_only": True,
                     "worker_pid": os.getpid(), "supervisor_pid": os.getppid(),
                     "native_execution_identity_proven": False, "native_sequence_proven": False})
        while time.monotonic() < plan.start_at:
            store.check()
            store.stop.wait(min(0.2, plan.start_at - time.monotonic()))
            store.health()
        store.active_at = time.monotonic()
        if args.command == "public-capture" and store.active_at - plan.start_at > 1:
            store.gap("late_start", seconds=store.active_at - plan.start_at)
        gate = RateGate(args.max_rest_rps, check=store.check, sleep=store.stop.wait)
        http = PublicHTTP(store, gate)
        if args.command == "readiness" and args.capture_health:
            reason = readiness_from_capture(args, store)
        elif args.command in ("public-capture", "readiness"):
            recorder = PublicCapture(args, store, http)
            if args.command == "readiness":
                reason = recorder.readiness()
            else:
                try:
                    recorder.run()
                finally:
                    joined = not recorder.stream.is_alive()
        else:
            through = args.through_utc or datetime.now(timezone.utc)
            store.write("account_cutoff", {"through_utc": through.isoformat()})
            reason = account_flow(args, store, http, int(through.timestamp()))
    except CaptureStopped as exc:
        reason = str(exc)
    except Exception as exc:
        store.fail("unhandled_error", error=type(exc).__name__)
    finally:
        try:
            receipt = store.close(reason)
            receipt["worker_threads_joined"] = joined
            lifeline.publish(receipt)
        finally:
            lifeline.close()
            channel.close()


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if args.command == "stop":
        from weather.market.pilot_evidence_launch import stop
        print(json.dumps(stop(args.output), indent=2))
        return 0
    if (args.max_rest_rps > 2 or args.max_rss_mib > 256 or not 2 <= args.max_output_mib <= 4096 or
            args.min_free_gib < 40):
        cli.error("hard limits: <=2 rps, <=256 MiB RSS, 2..4096 MiB output, >=40 GiB free")
    if args.command == "launch":
        from weather.market.pilot_evidence_launch import launch
        try:
            print(json.dumps(launch(args), indent=2))
        except (OSError, ValueError) as exc:
            cli.error(f"independent evidence launch refused: {type(exc).__name__}: {exc}")
        return 0
    if args.command == "readiness":
        args.market = ["denver", "toronto"]
        args.event_date = [args.session_date + timedelta(days=d) for d in (1, 2)]
        args.f0_commit = F0_COMMIT
    elif args.command == "public-capture":
        args.start_utc = args.start_utc or datetime.now(timezone.utc)
        if args.end_utc <= args.start_utc or args.end_utc <= datetime.now(timezone.utc):
            cli.error("end must follow start and be in the future")
        args.market, args.event_date = sorted(set(args.market)), sorted(set(args.event_date))
    elif (not re.fullmatch(r"0x[0-9a-fA-F]{40}", args.wallet) or args.max_pages < 1 or
          (args.through_utc and args.through_utc <= args.from_utc)):
        cli.error("valid wallet, page cap and increasing time bounds required")
    if args.command == "account-flow":
        live_start, live_end = utc("2026-11-08T23:55:00Z"), utc("2026-11-10T00:45:00Z")
        now = datetime.now(timezone.utc)
        if live_start <= now < live_end:
            cli.error("account export is refused during the public capture/live interval")
        if now < live_start:
            args.end_utc = live_start  # An earlier export must yield before the live interval too.
    if args.command == "readiness":
        if args.end_utc <= datetime.now(timezone.utc):
            cli.error("readiness end must be the future absolute capture end")
        if not args.capture_health and not args.pre_start:
            cli.error("network readiness requires --pre-start; active capture requires --capture-health")
        if args.capture_health and args.pre_start:
            cli.error("choose pre-start public readiness or active capture health")
    try:
        code, receipt = supervise(args, worker_main)
    except (OSError, ValueError) as exc:
        cli.error(f"evidence admission failed: {type(exc).__name__}: {exc}")
    print(json.dumps(receipt, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
