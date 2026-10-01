"""Offline calibration, ceiling measurement, rehearsal and manifest subcommands. No enrollment or score output."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import re
import time
from zoneinfo import ZoneInfo

from maker_core.replay import ceilings as ceiling_rule
from maker_core.replay.bundle import (BundleError, HOST_MAX_BYTES, HOST_MAX_RECORDS, HOST_MAX_SECONDS, Limits,
                                      _Reader)
from maker_core.replay.calibration import CALIBRATION_DATES, calibrate, unavailable_calibration
from maker_core.replay.engine import MAX_ENGINE_EVENTS, ReplayConfig, collect_stats
from maker_core.replay.execution_manifest import (FROZEN_CONFIG, build_manifest, quote_market_rule,
                                                  verify_manifest)
from maker_core.replay.execution_receipt import record_refusal
from maker_core.replay.pack_io import deadline, load_days, read_json, write_json

DEFAULT_LIMITS = dict(max_input_bytes=64*1024**2, max_records=100000, max_seconds=300.0, max_output_bytes=8*1024**2)


def _now():
    return datetime.now(timezone.utc)


def _limits(parser):
    # None means "not supplied": the default, or for a scored run the manifest's ceiling.
    parser.add_argument("--max-input-bytes", type=int)
    parser.add_argument("--max-records", type=int)
    parser.add_argument("--max-seconds", type=float)
    parser.add_argument("--max-output-bytes", type=int)


def limit_defaults(args):
    for name, value in DEFAULT_LIMITS.items():
        if getattr(args, name, None) is None:
            setattr(args, name, value)


def binding_arguments(parser):
    parser.add_argument("--calibration-bundle", type=Path, action="append", required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--quote-markets", type=Path, required=True)
    parser.add_argument("--ceiling-measurement", type=Path, required=True)


def add_commands(commands):
    markets = commands.add_parser("quote_markets", help="write the rule-derived quote-market set; no scores")
    markets.add_argument("--calibration-bundle", type=Path, action="append", required=True)
    markets.add_argument("--out", type=Path, required=True, help="new sorted city JSON array")
    _limits(markets)
    calibration = commands.add_parser("calibrate_hazard", help="seal the frozen public-trade hazard; no scores")
    calibration.add_argument("--bundle", type=Path, action="append", required=True)
    calibration.add_argument("--quote-markets", type=Path, required=True, help="sealed sorted city inventory JSON array")
    calibration.add_argument("--out", type=Path, required=True, help="new calibration JSON file")
    _limits(calibration)
    rehearsal = commands.add_parser("rehearse", help="score-free full-pipeline rehearsal of ONE calibration date; "
                                    "run each date in a fresh process")
    rehearsal.add_argument("--bundle", type=Path, required=True,
                           help="panel-format all-city bundle directory for one calibration date")
    rehearsal.add_argument("--calibration", type=Path, required=True, help="sealed calibration JSON (hazard)")
    rehearsal.add_argument("--out", type=Path, required=True, help="new resource-only JSON file")
    derive = commands.add_parser("derive_ceilings", help="Clarification 2 ceilings from the three date rehearsals")
    derive.add_argument("--rehearsal", type=Path, action="append", required=True)
    derive.add_argument("--out", type=Path, required=True, help="new ceiling measurement JSON file")
    manifest = commands.add_parser("manifest", help="build or preflight a complete manifest; does not enroll it")
    actions = manifest.add_subparsers(dest="manifest_action", required=True)
    for action in ("build", "verify"):
        child = actions.add_parser(action)
        child.add_argument("--bundle", type=Path, action="append", required=True)
        binding_arguments(child)
        for name in ("decision-log", "frozen-protocol", "execution-addendum", "clarification", "clarification-2"):
            child.add_argument("--"+name, type=Path, required=True)
        if action == "build":
            child.add_argument("--owner-decision", type=Path, required=True, help="exact Source JSON from the signed row")
            child.add_argument("--out", type=Path, required=True)
        else:
            child.add_argument("--manifest", type=Path, required=True)
            child.add_argument("--manifest-sha256", required=True)


def verification_args(args):
    return dict(calibration_path=args.calibration, inventory_path=args.universe,
                quote_inventory_path=args.quote_markets, measurement_path=args.ceiling_measurement,
                decision_log=args.decision_log, frozen_protocol=args.frozen_protocol,
                execution_addendum=args.execution_addendum, clarification=args.clarification,
                clarification_2=args.clarification_2)


def _maintenance(bundles):
    """The panel's 05:00-08:00 UTC exclusion, applied identically in a rehearsal."""
    projected = []
    for bundle in bundles:
        start = datetime.combine(bundle.day, datetime.min.time(), tzinfo=timezone.utc)
        low, high = start+timedelta(hours=5), start+timedelta(hours=8)
        windows = tuple((c.condition_id, a, b) for c in bundle.conditions
                        for a, b in ((c.active_from, min(c.active_until, low)), (max(c.active_from, high), c.active_until))
                        if a < b)
        projected.append(replace(bundle, active_intervals=windows))
    return tuple(projected)


def rehearse(paths, calibration_path, *, dates=CALIBRATION_DATES, now, clock=time.monotonic, memory=None):
    """Run the scored pipeline end to end and return resource counts only.

    Refuses every date outside ``dates`` before any bundle payload is read, so a
    quote-panel date can never be rehearsed. Scores stay in memory and are discarded.
    """
    from maker_core.replay.report import comparison_report, report_bytes
    started = clock()
    # Interpreter plus imports, before any input: the unmultiplied memory baseline.
    baseline = (memory or ceiling_rule.process_memory)()[1]
    check = deadline(HOST_MAX_SECONDS)
    allowed = {d.isoformat() for d in dates}
    for path in paths:
        # Exporters write <root>/<day>/bundle; a dated leaf names the date itself.
        path = Path(path)
        day = path.name if re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.name) else path.parent.name
        if day not in allowed:
            raise BundleError("rehearsal_restricted_to_calibration_dates")
    calibration, calibration_hash = read_json(calibration_path)
    if calibration.get("format") != "maker_core.replay.calibration.v1":
        raise BundleError("invalid_calibration_input")
    bundles = load_days(paths, Limits(HOST_MAX_BYTES, HOST_MAX_RECORDS, HOST_MAX_SECONDS), check, now=now)
    if any(b.day not in dates for b in bundles):
        raise BundleError("rehearsal_restricted_to_calibration_dates")
    config = ReplayConfig(**FROZEN_CONFIG, hazard_per_minute=float(calibration["hazard_per_minute"]),
                          max_events=MAX_ENGINE_EVENTS, max_outputs=MAX_ENGINE_EVENTS)
    with collect_stats() as passes:
        report = comparison_report(_maintenance(bundles), config, check=check)
        raw, markdown = report_bytes(report)  # Only the rendered size is kept.
    rendered = len(raw) + len(markdown)
    del report, raw, markdown
    runtime = clock()-started
    _, peak = (memory or ceiling_rule.process_memory)()
    measured = dict(input_bytes=sum(b.input_bytes for b in bundles), records=sum(len(b.records) for b in bundles),
                    engine_events=max((p["events"] for p in passes), default=0),
                    decisions_spans=max((p["decisions"]+p["spans"] for p in passes), default=0),
                    report_bytes=rendered, runtime_seconds=runtime,
                    peak_memory_above_baseline_bytes=max(0, peak-baseline), baseline_memory_bytes=baseline)
    detail = dict(dates=[b.day.isoformat() for b in bundles], conditions=sum(len(b.conditions) for b in bundles),
                  engine_passes=[dict(policy=p["policy"], fill_bound=p["fill_bound"], events=p["events"],
                                      decisions=p["decisions"], spans=p["spans"]) for p in passes],
                  input_hashes={b.day.isoformat(): dict(b.input_hashes) for b in bundles},
                  calibration_sha256=calibration_hash)
    return measured, detail


def execute(args):
    check, now = deadline(HOST_MAX_SECONDS), _now()
    if args.command == "rehearse":
        measured, detail = rehearse([args.bundle], args.calibration, now=now)
        key = write_json(args.out, dict(format=ceiling_rule.REHEARSAL_FORMAT, date=detail["dates"][0],
                         measured=measured, detail=detail, measured_at=now.isoformat(),
                         interpretation="Resource counts only; no score, fill, reward or hurdle value."))
        print("rehearsal_sha256="+key)
        return 0
    if args.command == "derive_ceilings":
        per_date, hashes, calibrations = {}, {}, set()
        for path in args.rehearsal:
            value, key = read_json(path)
            if (not isinstance(value, dict) or value.get("format") != ceiling_rule.REHEARSAL_FORMAT
                    or value.get("date") in per_date):
                raise BundleError("invalid_or_duplicate_rehearsal")
            per_date[value["date"]], hashes[value["date"]] = value["measured"], key
            calibrations.add(value["detail"]["calibration_sha256"])
        if len(calibrations) != 1:
            raise BundleError("rehearsals_used_different_calibrations")
        derived = ceiling_rule.derive(per_date)
        key = write_json(args.out, dict(format=ceiling_rule.FORMAT, per_date=per_date, rehearsal_sha256=hashes,
                         calibration_sha256=calibrations.pop(), derived=derived))
        print("ceiling_measurement_sha256="+key+"; executable_on_host="+str(derived["executable"])
              + ("" if derived["executable"] else "; binding="+",".join(derived["host_limit_binding"]))
              + "; verdict="+derived["verdict"])
        # The record is kept either way; a binding host limit stops the exam line here.
        return 0 if derived["executable"] else 3
    limit_defaults(args)
    if type(args.max_output_bytes) is not int or not 1 <= args.max_output_bytes <= 8*1024**2:
        raise BundleError("invalid_output_ceiling")
    if args.command == "quote_markets":
        limits = Limits(args.max_input_bytes, args.max_records, args.max_seconds)
        bundles = load_days(args.calibration_bundle, limits, deadline(limits.max_seconds), now=now)
        if tuple(b.day for b in bundles) != CALIBRATION_DATES:
            raise BundleError("calibration_requires_exact_three_dates")
        key = write_json(args.out, quote_market_rule(bundles), args.max_output_bytes)
        print("quote_markets_sha256="+key)
        return 0
    if args.command == "calibrate_hazard":
        limits = Limits(args.max_input_bytes, args.max_records, args.max_seconds)
        check = deadline(limits.max_seconds)
        markets, markets_hash = read_json(args.quote_markets)
        try:
            bundles = load_days(args.bundle, limits, check, now=now)
        except FileNotFoundError:
            report = unavailable_calibration(markets, "unavailable_calibration_files")
        else:
            if markets != quote_market_rule(bundles):
                raise BundleError("quote_markets_rule_mismatch")
            report = calibrate(bundles, markets, check=check)
        report["quote_inventory_sha256"] = markets_hash
        check()
        key = write_json(args.out, report, args.max_output_bytes)
        print("calibration_sha256="+key)
        return 0
    # Verify the signed row/documents before loading panel payloads, including in
    # build mode. Preflight allows an early verification, never early scoring.
    from maker_core.replay import authorization
    if args.manifest_action == "build":
        decision, _ = read_json(args.owner_decision, 65536)
        doc = dict(owner=decision.get("owner"), signed_at=decision.get("signed_at"), owner_decision=decision)
        root, key = args.out.parent / "attempts", None
    else:
        doc, key = read_json(args.manifest, 8*1024**2)
        if key != args.manifest_sha256:
            raise BundleError("execution_manifest_hash_mismatch")
        root = args.manifest.parent / "attempts"
    authorization._verify_decision(doc, _Reader(Limits(458752, 1, 5), time.monotonic),
        args.decision_log, args.frozen_protocol, args.execution_addendum, now, args.clarification,
        require_scoring_date=False, clarification_2=args.clarification_2)
    # Clarification 2: the manifest is built, verified and enrolled on or after the
    # scoring date (America/Toronto), once the settlement bundle is sealed.
    if now.astimezone(ZoneInfo("America/Toronto")).date() < date.fromisoformat(doc["owner_decision"]["scoring_date"]):
        raise BundleError("manifest_before_scoring_date_toronto")
    try:
        return _manifest(args, doc, key, now)
    except (ValueError, OSError, KeyError, TypeError, ArithmeticError, MemoryError) as exc:
        # The owner decision verified: an input, bundle, ceiling or host refusal here
        # is operational and prevents that day's look without consuming it.
        record_refusal(root, doc["owner_decision"]["authorization_id"], "manifest_"+args.manifest_action,
                       f"{type(exc).__name__}: {exc}", _now(), key)
        raise


def _manifest(args, doc, key, now):
    measurement, _ = read_json(args.ceiling_measurement)
    from maker_core.replay.execution_manifest import measured_limits
    run = measured_limits(measurement)
    limits = Limits(run["max_input_bytes"], run["max_records"], run["max_seconds"])
    check = ceiling_rule.guarded(deadline(limits.max_seconds), run["max_memory_bytes"])
    bundles = load_days(args.bundle, limits, check, now=now)
    remaining = Limits(limits.max_bytes-sum(b.input_bytes for b in bundles),
                       limits.max_records-sum(len(b.records) for b in bundles), limits.max_seconds)
    calibration_bundles = load_days(args.calibration_bundle, remaining, check, now=now)
    if args.manifest_action == "build":
        calibration, calibration_hash = read_json(args.calibration)
        inventory, inventory_hash = read_json(args.universe, 8*1024**2)
        markets, markets_hash = read_json(args.quote_markets)
        measurement, measurement_hash = read_json(args.ceiling_measurement)
        if not isinstance(calibration, dict) or markets != calibration.get("quote_markets"):
            raise BundleError("quote_inventory_mismatch")
        doc = build_manifest(bundles, calibration_bundles, calibration, inventory, doc["owner_decision"], measurement,
            calibration_sha256=calibration_hash, inventory_sha256=inventory_hash, quote_inventory_sha256=markets_hash,
            measurement_sha256=measurement_hash, check=check)
    verify_manifest(doc, bundles, calibration_bundles, **verification_args(args), now=now, check=check)
    check()
    if args.manifest_action == "build":
        key = write_json(args.out, doc, 8*1024**2)
    print("manifest_sha256="+key+"; VERIFIED_PREFLIGHT_ONLY; enrollment and scoring-date gates remain separate")
    return 0
