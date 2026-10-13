"""Registration draft §9-§11 calibration rehearsal subcommands (U5), reached through ``run.py``, the admitted entry.

    python -m tools.research.maker_replay_v2.run rehearsal-inventory --out NEW_DIR --bundle B [--bundle B ...]
    python -m tools.research.maker_replay_v2.run rehearse --out NEW_DIR --mode per_date|carried --bundle B [...]
        --inventory NEW_DIR_OF_INVENTORY/rehearsal-inventory.json --calibration CALIBRATION.json
        [--hazard-variant max_m|r1_per_city] [--replicates 2000]
    python -m tools.research.maker_replay_v2.run derive --out NEW_DIR --per-date A B C --carried D
    python -m tools.research.maker_replay_v2.run gate-report --out NEW_DIR --per-date A B C --carried D
        --repeat-rehearsal E [--r1 F] [--e1 G] [--e3 H] [--e8 I]

Calibration dates (2026-09-27..29) only: every bundle path is checked by name before a byte is read
(``rehearsal.calibration_day``), and every input document is bounded (``pack_io.read_json``). One subcommand per
fresh process, serially, through ``scripts/ops/workstation_heavy.ps1``:

- ``rehearsal-inventory``: the universe inventory rows (``weather.market.maker_replay_universe_v02.universe``) for
  exactly the rehearsed dates: one date for a per-date rehearsal, the three for the carried one (the inventory must
  equal the conditions discovered in the dates evaluated, ``universe_discovery_mismatch``). Its own process, so the
  rehearsal's memory baseline is not raised by the inventory read.
- ``rehearse``: one score-free rehearsal (``rehearsal.rehearse``); the hazard scalar and, for R1, the per-city map
  come from the unchanged calibration document (``reachability.hazards``); ``calibration_sha256`` is that file's
  SHA-256. The inventory's dates must be the bundles' dates.
- ``derive``: ``ceilings.derive`` and gate E5 from the three per-date documents and the carried one.
- ``gate-report``: ``reachability.gate_report`` (§10 E1-E8 and §11). ``--e1/--e3/--e8`` are JSON files
  ``{"status": "PASS"|"FAIL", "evidence": "..."}``; an absent one reads NOT_SUPPLIED.

Every output is counts, fractions and hashes only (the rehearsal whitelist); no score, fill, P&L or contrast is
written.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from maker_core.replay.bundle import BundleError
from maker_core.replay.calibration import CALIBRATION_DATES
from maker_core.replay.pack_io import read_json

INVENTORY_FORMAT = "maker_core.replay.v2.rehearsal_inventory.v0.1"
DERIVED_FORMAT = "maker_core.replay.v2.rehearsal_derived.v0.1"
SUBCOMMANDS = ("rehearsal-inventory", "rehearse", "derive", "gate-report")
DOCUMENT_BYTES = 4 * 1024**2  # inventories are the largest input: at most 30,000 rows


def add_arguments(parser):
    parser.add_argument("--bundle", type=Path, action="append", default=[],
                        help="rehearsal-inventory/rehearse: a calibration bundle folder (<root>/<date>/bundle)")
    parser.add_argument("--inventory", type=Path, help="rehearse: a rehearsal-inventory output for these dates")
    parser.add_argument("--calibration", type=Path, help="rehearse: the unchanged calibration document")
    parser.add_argument("--mode", choices=("per_date", "carried"), help="rehearse: one date or the three")
    parser.add_argument("--hazard-variant", choices=("max_m", "r1_per_city"), default="max_m")
    parser.add_argument("--replicates", type=int, default=2000, help="rehearse: bootstrap replicates (reg §12)")
    parser.add_argument("--per-date", type=Path, nargs=3, help="derive/gate-report: the three per-date rehearsals")
    parser.add_argument("--carried", type=Path, help="derive/gate-report: the carried max_m rehearsal")
    parser.add_argument("--repeat-rehearsal", type=Path, help="gate-report: a second per-date rehearsal (E7)")
    parser.add_argument("--r1", type=Path, help="gate-report: the carried r1_per_city rehearsal (only if §11 fails)")
    for gate in ("e1", "e3", "e8"):
        parser.add_argument(f"--{gate}", type=Path, help=f"gate-report: {gate.upper()} evidence JSON")


def _document(path):
    if path is None:
        return None, None
    return read_json(path, DOCUMENT_BYTES)


def _days(paths):
    from maker_core.replay.v2.rehearsal import calibration_day
    days = [calibration_day(path) for path in paths]  # by name, before any byte is read
    if not paths or len(set(days)) != len(days):
        raise BundleError("rehearsal_bundle_paths_invalid")
    return sorted(days)


def rehearsal_inventory(args):
    from weather.market.maker_replay_universe_v02 import universe
    days = _days(args.bundle)
    if len(days) not in (1, len(CALIBRATION_DATES)):
        raise BundleError("rehearsal_bundle_paths_invalid")
    rows = universe([], args.bundle)
    return dict(format=INVENTORY_FORMAT, dates=[d.isoformat() for d in days], rows=rows)


def rehearse(args, *, now=None, memory=None):
    from maker_core.replay.v2 import reachability, rehearsal
    days = _days(args.bundle)
    inventory, _ = _document(args.inventory)
    calibration, calibration_sha256 = _document(args.calibration)
    if inventory is None or calibration is None or args.mode is None:
        raise BundleError("rehearse_needs_mode_inventory_and_calibration")
    if (not isinstance(inventory, dict) or inventory.get("format") != INVENTORY_FORMAT
            or inventory.get("dates") != [d.isoformat() for d in days] or not isinstance(inventory.get("rows"), list)):
        raise BundleError("rehearsal_inventory_dates_mismatch")
    scalar, by_market = reachability.hazards(calibration, args.hazard_variant)
    return rehearsal.rehearse(args.bundle, inventory["rows"], mode=args.mode, hazard_per_minute=scalar,
                              hazard_by_market=by_market, hazard_variant=args.hazard_variant,
                              calibration_sha256=calibration_sha256, replicates=args.replicates,
                              now=now or datetime.now(timezone.utc), memory=memory)


def _rehearsals(args):
    if args.per_date is None or args.carried is None:
        raise BundleError("rehearsal_documents_required")
    per_date = {}
    for path in args.per_date:
        doc, _ = _document(path)
        day = (doc.get("dates") or [None])[0] if isinstance(doc, dict) else None
        if day in per_date or day is None:
            raise BundleError("gate_per_date_rehearsal_required:" + str(day))
        per_date[day] = doc
    carried, _ = _document(args.carried)
    return per_date, carried


def derive(args):
    from maker_core.replay.v2 import ceilings
    from maker_core.replay.v2.rehearsal import ceiling_input
    per_date, carried = _rehearsals(args)
    if carried.get("mode") != "carried":
        raise BundleError("gate_carried_rehearsal_required:max_m")
    measured = {day: ceiling_input(doc) for day, doc in per_date.items()}
    derived = ceilings.derive(measured, ceiling_input(carried))
    return dict(format=DERIVED_FORMAT, derived=derived, e5=ceilings.e5_memory(measured, ceiling_input(carried), derived),
                run_limits=ceilings.run_limits(derived) if derived["executable"] else None)


def gate_report(args):
    from maker_core.replay.v2 import reachability
    per_date, carried = _rehearsals(args)
    repeat, _ = _document(args.repeat_rehearsal)
    if repeat is None:
        raise BundleError("gate_repeat_rehearsal_required")
    r1, _ = _document(args.r1)
    evidence = {gate: _document(getattr(args, gate))[0] for gate in ("e1", "e3", "e8")}
    return reachability.gate_report(per_date, carried, repeat, r1=r1, **evidence)


def run(name, args):
    """The result document of one subcommand; ``run.py`` writes it under ``--out``."""
    return dict(zip(SUBCOMMANDS, (rehearsal_inventory, rehearse, derive, gate_report)))[name](args)
