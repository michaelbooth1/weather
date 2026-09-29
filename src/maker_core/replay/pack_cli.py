"""Offline calibration and manifest subcommands. No enrollment or score output."""
from datetime import datetime, timezone
from pathlib import Path

from maker_core.replay.bundle import BundleError, Limits, _Reader
from maker_core.replay.calibration import calibrate, unavailable_calibration
from maker_core.replay.execution_manifest import build_manifest, verify_manifest
from maker_core.replay.pack_io import deadline, load_days, read_json, write_json


def _now():
    return datetime.now(timezone.utc)


def _limits(parser):
    parser.add_argument("--max-input-bytes", type=int, default=64*1024**2)
    parser.add_argument("--max-records", type=int, default=100000)
    parser.add_argument("--max-seconds", type=float, default=300)
    parser.add_argument("--max-output-bytes", type=int, default=8*1024**2)


def binding_arguments(parser):
    parser.add_argument("--calibration-bundle", type=Path, action="append", required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--quote-markets", type=Path, required=True)


def add_commands(commands):
    calibration = commands.add_parser("calibrate_hazard", help="seal the frozen public-trade hazard; no scores")
    calibration.add_argument("--bundle", type=Path, action="append", required=True)
    calibration.add_argument("--quote-markets", type=Path, required=True, help="sealed sorted city inventory JSON array")
    calibration.add_argument("--out", type=Path, required=True, help="new calibration JSON file")
    _limits(calibration)
    manifest = commands.add_parser("manifest", help="build or preflight a complete manifest; does not enroll it")
    actions = manifest.add_subparsers(dest="manifest_action", required=True)
    for action in ("build", "verify"):
        child = actions.add_parser(action)
        child.add_argument("--bundle", type=Path, action="append", required=True)
        binding_arguments(child)
        for name in ("decision-log", "frozen-protocol", "execution-addendum", "clarification"):
            child.add_argument("--"+name, type=Path, required=True)
        if action == "build":
            child.add_argument("--owner-decision", type=Path, required=True, help="exact Source JSON from the signed row")
            child.add_argument("--out", type=Path, required=True)
        else:
            child.add_argument("--manifest", type=Path, required=True)
            child.add_argument("--manifest-sha256", required=True)
        _limits(child)


def verification_args(args):
    return dict(calibration_path=args.calibration, inventory_path=args.universe,
                quote_inventory_path=args.quote_markets, decision_log=args.decision_log,
                frozen_protocol=args.frozen_protocol, execution_addendum=args.execution_addendum,
                clarification=args.clarification)


def execute(args):
    limits = Limits(args.max_input_bytes, args.max_records, args.max_seconds)
    check, now = deadline(limits.max_seconds), _now()
    if type(args.max_output_bytes) is not int or not 1 <= args.max_output_bytes <= 8*1024**2:
        raise BundleError("invalid_output_ceiling")
    if args.command == "calibrate_hazard":
        markets, markets_hash = read_json(args.quote_markets)
        try:
            bundles = load_days(args.bundle, limits, check, now=now)
        except FileNotFoundError:
            report = unavailable_calibration(markets, "unavailable_calibration_files")
        else:
            report = calibrate(bundles, markets, check=check)
        report["quote_inventory_sha256"] = markets_hash
        check()
        key = write_json(args.out, report, args.max_output_bytes)
        print("calibration_sha256="+key)
        return 0
    # Verify the signed row/documents before loading panel payloads, including in
    # build mode. Preflight allows an early verification, never early scoring.
    from maker_core.replay import authorization
    import time
    if args.manifest_action == "build":
        decision, _ = read_json(args.owner_decision, 65536)
        doc = dict(owner=decision.get("owner"), signed_at=decision.get("signed_at"), owner_decision=decision)
    else:
        doc, key = read_json(args.manifest, 8*1024**2)
        if key != args.manifest_sha256:
            raise BundleError("execution_manifest_hash_mismatch")
    authorization._verify_decision(doc, _Reader(Limits(458752, 1, 5), time.monotonic),
        args.decision_log, args.frozen_protocol, args.execution_addendum, now, args.clarification,
        require_scoring_date=False)
    bundles = load_days(args.bundle, limits, check, now=now)
    remaining = Limits(limits.max_bytes-sum(b.input_bytes for b in bundles),
                       limits.max_records-sum(len(b.records) for b in bundles), limits.max_seconds)
    calibration_bundles = load_days(args.calibration_bundle, remaining, check, now=now)
    if args.manifest_action == "build":
        calibration, calibration_hash = read_json(args.calibration)
        inventory, inventory_hash = read_json(args.universe, 8*1024**2)
        markets, markets_hash = read_json(args.quote_markets)
        if markets != calibration.get("quote_markets"):
            raise BundleError("quote_inventory_mismatch")
        doc = build_manifest(bundles, calibration_bundles, calibration, inventory, decision,
            calibration_sha256=calibration_hash, inventory_sha256=inventory_hash, quote_inventory_sha256=markets_hash,
            limits=limits, max_output_bytes=args.max_output_bytes, check=check)
    verify_manifest(doc, bundles, calibration_bundles, **verification_args(args), now=now, check=check)
    check()
    if args.manifest_action == "build":
        key = write_json(args.out, doc, args.max_output_bytes)
    print("manifest_sha256="+key+"; VERIFIED_PREFLIGHT_ONLY; enrollment and scoring-date gates remain separate")
    return 0
