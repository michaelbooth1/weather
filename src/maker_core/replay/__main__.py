"""Bounded replay CLI; comparison requires a pinned manifest and owner decision-log row."""
import argparse
from pathlib import Path
import time

from maker_core.replay.bundle import BundleError, Limits, load_bundle, regular_path
from maker_core.replay.diagnostics import MAX_REPORT_BYTES, coverage_report, write_report
from maker_core.replay.authorization import read_authorization, bind_scope
from maker_core.replay.engine import ReplayConfig
from maker_core.replay.report import comparison_report, report_bytes
from maker_core.replay import pack_cli

EXECUTION_PREFIX = "maker_core.replay.execution."
REFUSALS = (ValueError, OSError, KeyError, TypeError, ArithmeticError, MemoryError)


def _output_preflight(out, bundles):
    """A report directory problem must refuse before the look, never after scoring."""
    out = regular_path(out)
    if out.exists() or not out.parent.is_dir():
        raise BundleError("report_output_must_be_new_directory_under_existing_parent")
    for path in bundles:
        source = regular_path(path)
        if out == source or out.is_relative_to(source) or source.is_relative_to(out):
            raise BundleError("output_input_overlap")


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
    run.add_argument("--clarification-2", type=Path, help="Clarification 2, required by a v2 authorization")
    run.add_argument("--calibration-bundle", type=Path, action="append")
    run.add_argument("--calibration", type=Path)
    run.add_argument("--universe", type=Path)
    run.add_argument("--quote-markets", type=Path)
    run.add_argument("--ceiling-measurement", type=Path)
    run.add_argument("--hazard-per-minute", type=float)
    run.add_argument("--initial-cash", default="100")
    run.add_argument("--bootstrap-replicates", type=int, default=2000)
    run.add_argument("--bootstrap-seed", type=int, default=20260926)
    # Unset limits take the defaults, or for a scored execution run the manifest's ceilings.
    run.add_argument("--max-input-bytes", type=int)
    run.add_argument("--max-output-bytes", type=int)
    run.add_argument("--max-records", type=int)
    run.add_argument("--max-seconds", type=float)
    args = parser.parse_args(argv)
    if args.command != "run":
        try:
            return pack_cli.execute(args)
        except REFUSALS as exc:
            parser.exit(2, f"replay refused: {exc}\n")
    # A user-supplied hash or synthetic label cannot enroll an approval.
    if args.diagnostic_only and (args.pre_registration or args.pre_registration_sha256
                                or args.decision_log or args.frozen_protocol or args.execution_addendum
                                or args.clarification or args.clarification_2 or args.calibration_bundle
                                or args.calibration or args.universe or args.quote_markets
                                or args.ceiling_measurement):
        parser.error("registration flags require explicit --compare; use diagnostic-only without registration flags")
    if len(args.bundle) > 366:
        parser.error("at most 366 closed UTC days")
    started = time.monotonic()
    supplied = {name: getattr(args, name) for name in pack_cli.DEFAULT_LIMITS}
    stage, attempt, registration, refusal_root = "authorization", None, None, None
    try:
        from maker_core.replay.execution_receipt import late_look_permitted
        registration = (None if args.diagnostic_only else
                        read_authorization(args.pre_registration, args.pre_registration_sha256,
                                           decision_log=args.decision_log, frozen_protocol=args.frozen_protocol,
                                           execution_addendum=args.execution_addendum, clarification=args.clarification,
                                           clarification_2=args.clarification_2,
                                           late_look=lambda doc: late_look_permitted(args.pre_registration, doc)))
        fmt = registration.get("format") if registration else None
        execution = isinstance(fmt, str) and fmt.startswith(EXECUTION_PREFIX)
        memory_ceiling = None
        if execution:
            from maker_core.replay.execution_manifest import FORMAT
            if fmt != FORMAT:
                raise BundleError("superseded_execution_manifest_format")
            # Authorization verified: later refusals before reservation are recorded, not consumed.
            refusal_root = Path(args.pre_registration).parent / "attempts"
            stage = "ceiling_binding"
            ceilings = registration["ceilings"]
            for name, value in supplied.items():
                if value is not None and value != ceilings[name]:
                    raise BundleError("execution_ceiling_mismatch")
                setattr(args, name, ceilings[name])
            memory_ceiling = ceilings["max_memory_bytes"]
        else:
            pack_cli.limit_defaults(args)
        limits = Limits(args.max_input_bytes, args.max_records, args.max_seconds)

        def deadline():
            if time.monotonic() - started >= args.max_seconds:
                raise BundleError("time_cap")
        check = deadline
        if execution:
            from maker_core.replay import ceilings as ceiling_rule
            check = ceiling_rule.guarded(deadline, memory_ceiling)
            stage = "output_preflight"
            _output_preflight(args.out, args.bundle)
            stage = "host_preflight"
            ceiling_rule.host_preflight()
            ceiling_rule.window_preflight(pack_cli._now(), args.max_seconds)
        if args.diagnostic_only and len(args.bundle) != 1:
            raise BundleError("diagnostic_mode_requires_one_bundle_per_report")
        stage = "input"
        bundles, remaining_bytes, remaining_records = [], limits.max_bytes, limits.max_records
        for path in args.bundle:
            check()
            bundle = load_bundle(path, limits=Limits(remaining_bytes, remaining_records, limits.max_seconds))
            remaining_bytes -= bundle.input_bytes
            remaining_records -= len(bundle.records)
            bundles.append(bundle)
        if args.diagnostic_only:
            stage = "diagnostic"
            report = coverage_report(bundles[0], args.policy, check=check)
            write_report(args.out, report, input_directory=args.bundle[0],
                         max_bytes=args.max_output_bytes, check=check)
            return 0
        config = ReplayConfig(hazard_per_minute=args.hazard_per_minute, initial_cash=args.initial_cash)
        if execution:
            from maker_core.replay.execution_manifest import verify_manifest, apply_manifest
            from maker_core.replay.pack_io import load_days
            stage = "manifest_verification"
            if not all((args.calibration_bundle, args.calibration, args.universe, args.quote_markets,
                        args.ceiling_measurement)):
                raise BundleError("execution_binding_paths_required")
            calibration_bundles = load_days(args.calibration_bundle,
                Limits(remaining_bytes, remaining_records, limits.max_seconds), check, now=pack_cli._now())
            verify_manifest(registration, bundles, calibration_bundles, **pack_cli.verification_args(args),
                            now=pack_cli._now(), check=check)
            config = ReplayConfig(**registration["replay_config"])
            if ((args.hazard_per_minute is not None and args.hazard_per_minute != config.hazard_per_minute)
                    or str(config.initial_cash) != args.initial_cash):
                raise BundleError("execution_config_override")
            bundles = apply_manifest(registration, bundles)
        stage = "scope_binding"
        bind_scope(registration, bundles, config, args.bootstrap_replicates, args.bootstrap_seed)
        if execution:
            from maker_core.replay.engine import ReplayEngine
            from maker_core.replay.execution_receipt import reserve_attempt
            from maker_core.replay.execution_manifest import source_hashes
            # Structural engine checks (days, calendar span, event ceiling) need no policy call.
            stage = "engine_preflight"
            ReplayEngine(tuple(bundles), config, check=check)
            # Recheck revocation, raw manifest and document bytes at the action boundary.
            stage = "action_boundary"
            read_authorization(args.pre_registration, args.pre_registration_sha256,
                decision_log=args.decision_log, frozen_protocol=args.frozen_protocol,
                execution_addendum=args.execution_addendum, clarification=args.clarification,
                clarification_2=args.clarification_2,
                late_look=lambda doc: late_look_permitted(args.pre_registration, doc))
            current = source_hashes(check=check)
            if current != registration["source_hashes"]:
                changed = sorted(set(current) ^ set(registration["source_hashes"]) or
                                 {k for k in current if current[k] != registration["source_hashes"][k]})
                raise BundleError("executable_sources_changed_before_policy:" + ",".join(changed[:5]))
            # The first policy replay computes fills: the look is consumed from here on.
            stage = "reservation"
            attempt = reserve_attempt(args.pre_registration, registration, args.pre_registration_sha256, pack_cli._now())
        stage = "scoring"
        report = comparison_report(bundles, config, replicates=args.bootstrap_replicates,
                                   seed=args.bootstrap_seed, registration_hash=args.pre_registration_sha256, check=check)
        report["owner_registration"] = registration
        if attempt is not None:
            from maker_core.replay.execution_receipt import evaluate_hurdles
            stage = "decision"
            report["registered_decision"] = evaluate_hurdles(report)
            report["attempt_receipt"] = attempt.name
        stage = "report_output"
        write_report(args.out, report, input_directory=args.bundle[0], other_inputs=args.bundle[1:],
                     max_bytes=args.max_output_bytes, check=check, render=report_bytes)
        if attempt is not None:
            from maker_core.replay.pack_io import write_json
            write_json(attempt.with_suffix(".completed.json"), dict(status="COMPLETED", manifest_sha256=args.pre_registration_sha256,
                completed_at=pack_cli._now().isoformat(), registered_decision=report["registered_decision"]))
    except REFUSALS as exc:
        reason = f"{type(exc).__name__}: {exc}"
        try:
            from maker_core.replay.execution_receipt import record_refusal, record_stop
            if attempt is not None:
                record_stop(attempt, stage, reason, pack_cli._now())
            elif refusal_root is not None and stage != "reservation":
                record_refusal(refusal_root, registration["owner_decision"]["authorization_id"], stage, reason,
                               pack_cli._now(), args.pre_registration_sha256)
        except REFUSALS as record_exc:
            reason += f"; stage record failed: {record_exc}"
        parser.exit(2, f"replay refused at {stage}: {reason}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
