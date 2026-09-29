"""Bounded replay CLI; comparison requires a pinned manifest and owner decision-log row."""
import argparse
from pathlib import Path
import time

from maker_core.replay.bundle import BundleError, Limits, load_bundle
from maker_core.replay.diagnostics import MAX_REPORT_BYTES, coverage_report, write_report
from maker_core.replay.authorization import read_authorization, bind_scope
from maker_core.replay.engine import ReplayConfig
from maker_core.replay.report import comparison_report, report_bytes
from maker_core.replay import pack_cli


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pack_cli.add_commands(commands)
    run = commands.add_parser("run", help="validate one closed UTC day and report capture coverage")
    run.add_argument("--bundle", type=Path, required=True, action="append")
    run.add_argument("--out", type=Path, required=True, help="new directory under an existing parent")
    run.add_argument("--policy", choices=("no_quote", "blind_re1", "clock_only", "informed-v0"),
                     default="no_quote", help="recorded only; diagnostic mode executes no policy")
    mode = run.add_mutually_exclusive_group()
    mode.add_argument("--diagnostic-only", dest="diagnostic_only", action="store_true", default=True)
    mode.add_argument("--compare", dest="diagnostic_only", action="store_false")
    run.add_argument("--pre-registration", type=Path)
    run.add_argument("--pre-registration-sha256")
    run.add_argument("--decision-log", type=Path, help="reviewed owner decision log")
    run.add_argument("--frozen-protocol", type=Path, help="frozen hurdle Markdown file")
    run.add_argument("--execution-addendum", type=Path, help="frozen execution-method Markdown file")
    run.add_argument("--clarification", type=Path, help="optional owner-attested clarification")
    run.add_argument("--calibration-bundle", type=Path, action="append")
    run.add_argument("--calibration", type=Path)
    run.add_argument("--universe", type=Path)
    run.add_argument("--quote-markets", type=Path)
    run.add_argument("--hazard-per-minute", type=float)
    run.add_argument("--initial-cash", default="100")
    run.add_argument("--bootstrap-replicates", type=int, default=2000)
    run.add_argument("--bootstrap-seed", type=int, default=20260926)
    run.add_argument("--max-input-bytes", type=int, default=64 * 1024**2)
    run.add_argument("--max-output-bytes", type=int, default=MAX_REPORT_BYTES)
    run.add_argument("--max-records", type=int, default=100_000)
    run.add_argument("--max-seconds", type=float, default=300.0)
    args = parser.parse_args(argv)
    if args.command != "run":
        try:
            return pack_cli.execute(args)
        except (ValueError, OSError, KeyError, TypeError, ArithmeticError) as exc:
            parser.exit(2, f"replay refused: {exc}\n")
    # A user-supplied hash or synthetic label cannot enroll an approval.
    if args.diagnostic_only and (args.pre_registration or args.pre_registration_sha256
                                or args.decision_log or args.frozen_protocol or args.execution_addendum
                                or args.clarification or args.calibration_bundle or args.calibration
                                or args.universe or args.quote_markets):
        parser.error("registration flags require explicit --compare; use diagnostic-only without registration flags")
    if len(args.bundle) > 366:
        parser.error("at most 366 closed UTC days")
    started = time.monotonic()

    def check():
        if time.monotonic() - started >= args.max_seconds:
            raise BundleError("time_cap")

    try:
        registration = (None if args.diagnostic_only else
                        read_authorization(args.pre_registration, args.pre_registration_sha256,
                                           decision_log=args.decision_log, frozen_protocol=args.frozen_protocol,
                                           execution_addendum=args.execution_addendum, clarification=args.clarification))
        if args.diagnostic_only and len(args.bundle) != 1:
            raise BundleError("diagnostic_mode_requires_one_bundle_per_report")
        limits = Limits(args.max_input_bytes, args.max_records, args.max_seconds)
        bundles, remaining_bytes, remaining_records = [], limits.max_bytes, limits.max_records
        for path in args.bundle:
            check()
            bundle = load_bundle(path, limits=Limits(remaining_bytes, remaining_records, limits.max_seconds))
            remaining_bytes -= bundle.input_bytes
            remaining_records -= len(bundle.records)
            bundles.append(bundle)
        if args.diagnostic_only:
            report = coverage_report(bundles[0], args.policy, check=check)
            write_report(args.out, report, input_directory=args.bundle[0],
                         max_bytes=args.max_output_bytes, check=check)
        else:
            config = ReplayConfig(hazard_per_minute=args.hazard_per_minute, initial_cash=args.initial_cash)
            if registration.get("format") == "maker_core.replay.execution.v1":
                from maker_core.replay.execution_manifest import verify_manifest, apply_manifest
                from maker_core.replay.pack_io import load_days
                if not all((args.calibration_bundle, args.calibration, args.universe, args.quote_markets)):
                    raise BundleError("execution_binding_paths_required")
                calibration_bundles = load_days(args.calibration_bundle,
                    Limits(remaining_bytes, remaining_records, limits.max_seconds), check, now=pack_cli._now())
                verify_manifest(registration, bundles, calibration_bundles, **pack_cli.verification_args(args),
                                now=pack_cli._now(), check=check)
                if registration["ceilings"] != dict(max_input_bytes=args.max_input_bytes, max_records=args.max_records,
                    max_seconds=args.max_seconds, max_output_bytes=args.max_output_bytes):
                    raise BundleError("execution_ceiling_mismatch")
                config = ReplayConfig(**registration["replay_config"])
                if ((args.hazard_per_minute is not None and args.hazard_per_minute != config.hazard_per_minute)
                        or str(config.initial_cash) != args.initial_cash):
                    raise BundleError("execution_config_override")
                bundles = apply_manifest(registration, bundles)
            bind_scope(registration, bundles, config, args.bootstrap_replicates, args.bootstrap_seed)
            attempt = None
            if registration.get("format") == "maker_core.replay.execution.v1":
                from maker_core.replay.execution_receipt import reserve_attempt, evaluate_hurdles
                # Recheck revocation, raw manifest and document bytes at the action boundary.
                read_authorization(args.pre_registration, args.pre_registration_sha256,
                    decision_log=args.decision_log, frozen_protocol=args.frozen_protocol,
                    execution_addendum=args.execution_addendum, clarification=args.clarification)
                from maker_core.replay.execution_manifest import source_hashes
                if source_hashes(check=check) != registration["source_hashes"]:
                    raise BundleError("executable_sources_changed_before_policy")
                attempt = reserve_attempt(args.pre_registration, registration, args.pre_registration_sha256, pack_cli._now())
            report = comparison_report(bundles, config, replicates=args.bootstrap_replicates,
                                       seed=args.bootstrap_seed, registration_hash=args.pre_registration_sha256, check=check)
            report["owner_registration"] = registration
            if attempt is not None:
                from maker_core.replay.pack_io import write_json
                report["registered_decision"] = evaluate_hurdles(report)
                report["attempt_receipt"] = attempt.name
            write_report(args.out, report, input_directory=args.bundle[0], other_inputs=args.bundle[1:],
                         max_bytes=args.max_output_bytes, check=check, render=report_bytes)
            if attempt is not None:
                write_json(attempt.with_suffix(".completed.json"), dict(status="COMPLETED", manifest_sha256=args.pre_registration_sha256,
                    completed_at=pack_cli._now().isoformat(), registered_decision=report["registered_decision"]))
    except (ValueError, OSError, KeyError, TypeError, ArithmeticError) as exc:
        parser.exit(2, f"replay refused: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
