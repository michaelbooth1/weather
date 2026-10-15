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
- ``derive``: ``ceilings.derive`` and gate E5 from the three per-date documents and the carried one (whose top-level
  ``pull_candidates`` gives the §9 pull-candidate ceiling; a carried document without it refuses).
- ``gate-report``: ``reachability.gate_report`` (§10 E1-E8 and §11). ``--e1/--e3/--e8`` are JSON files
  ``{"status": "PASS"|"FAIL", "evidence": "..."}``; an absent one reads NOT_SUPPLIED.

Every output is counts, fractions and hashes only (the rehearsal whitelist); no score, fill, P&L or contrast is
written. ``guarded`` (CONSOLIDATED row 16, binding: DECISION_LOG 2026-10-15) covers what reaches stdout and stderr:
every rehearsal document read is re-checked against the typed schema (``rehearsal.whitelisted``), a ``rehearse``
result is re-checked before it is written or printed, every result is scanned for forbidden keys at any depth, and
a refusal prints only ``refused: <code>`` on stderr: the code's path keeps schema names, calibration dates and
indices, and replaces anything else with ``<key>``; no traceback, exception text or warning is printed.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
import re
import warnings

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


def _rehearsal(path):
    """A written rehearsal document, re-checked against the typed schema on read (row 16)."""
    from maker_core.replay.v2.rehearsal import whitelisted
    doc, _ = _document(path)
    return doc if doc is None else whitelisted(doc)


def _rehearsals(args):
    if args.per_date is None or args.carried is None:
        raise BundleError("rehearsal_documents_required")
    per_date = {}
    for path in args.per_date:
        doc = _rehearsal(path)
        day = (doc.get("dates") or [None])[0] if isinstance(doc, dict) else None
        if day in per_date or day is None:
            raise BundleError("gate_per_date_rehearsal_required:" + str(day))
        per_date[day] = doc
    return per_date, _rehearsal(args.carried)


def derive(args):
    from maker_core.replay.v2 import ceilings
    from maker_core.replay.v2.rehearsal import ceiling_input
    per_date, carried = _rehearsals(args)
    for day, doc in per_date.items():  # the same labels gate_report requires (Defender D7.2)
        if doc.get("mode") != "per_date" or doc.get("dates") != [day] or doc.get("hazard_variant") != "max_m":
            raise BundleError("gate_per_date_rehearsal_required:" + str(day))
    if not isinstance(carried, dict) or carried.get("mode") != "carried" or carried.get("hazard_variant") != "max_m":
        raise BundleError("gate_carried_rehearsal_required:max_m")
    measured = {day: ceiling_input(doc) for day, doc in per_date.items()}
    derived = ceilings.derive(measured, ceiling_input(carried), pull_candidates=carried.get("pull_candidates"))
    return dict(format=DERIVED_FORMAT, derived=derived, e5=ceilings.e5_memory(measured, ceiling_input(carried), derived),
                run_limits=ceilings.run_limits(derived) if derived["executable"] else None)


def gate_report(args):
    from maker_core.replay.v2 import reachability
    per_date, carried = _rehearsals(args)
    repeat = _rehearsal(args.repeat_rehearsal)
    if repeat is None:
        raise BundleError("gate_repeat_rehearsal_required")
    r1 = _rehearsal(args.r1)
    evidence = {gate: _document(getattr(args, gate))[0] for gate in ("e1", "e3", "e8")}
    return reachability.gate_report(per_date, carried, repeat, r1=r1, **evidence)


def run(name, args):
    """The result document of one subcommand; ``run.py`` writes it under ``--out``."""
    return dict(zip(SUBCOMMANDS, (rehearsal_inventory, rehearse, derive, gate_report)))[name](args)


_CODE = re.compile(r"[a-z][a-z0-9_]{0,79}")
_INDEX = re.compile(r"\[\d{1,6}\]")
_NAMES = []


def _names():
    """Every name a refusal path may echo: schema keys, forbidden keys, gate and variant names, calibration dates."""
    if not _NAMES:
        from maker_core.replay.v2 import rehearsal
        names = set(rehearsal.FORBIDDEN) | {f"E{i}" for i in range(1, 9)} | set(rehearsal.HAZARD_VARIANTS)
        names |= {d.isoformat() for d in CALIBRATION_DATES} | {"<key>", ""}

        def collect(spec):
            if isinstance(spec, dict):
                for key, child in spec.items():
                    names.add(key)
                    collect(child)
            elif isinstance(spec, (rehearsal.MapOf, rehearsal.ListOf, rehearsal.Nullable)):
                collect(getattr(spec, "value", getattr(spec, "item", getattr(spec, "spec", None))))
        collect(rehearsal.schema())
        _NAMES.append(frozenset(names))
    return _NAMES[0]


def refusal_code(exc):
    """What a refusal may print: the code, and its path with every segment that is not a known name masked."""
    coded = isinstance(exc, (BundleError, ValueError)) and not isinstance(exc, UnicodeError)  # raised with a code
    text = str(exc.args[0]) if coded and exc.args and isinstance(exc.args[0], str) else ""
    head, _, rest = text.partition(":")
    if _CODE.fullmatch(head) is None:
        return "error:" + type(exc).__name__
    if not rest:
        return head
    segments = [_INDEX.sub("", s) for s in rest[:400].split(".")]
    indices = [_INDEX.findall(s) for s in rest[:400].split(".")]
    shown = [(s if s in _names() else "<key>") + "".join(i) for s, i in zip(segments, indices)]
    return head + ":" + ".".join(shown)


def forbidden_keys(value, path=""):
    """Every path in ``value`` whose key is a forbidden (score) key, at any depth."""
    from maker_core.replay.v2.rehearsal import FORBIDDEN
    found = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            where = f"{path}.{key}" if path else str(key)
            found += [where] if str(key) in FORBIDDEN else forbidden_keys(item, where)
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            found += forbidden_keys(item, f"{path}[{i}]")
    return found


def guarded(name, args):
    """(result, None) or (None, refusal code): ``run`` with the output guard of row 16 (see the module docstring).

    Warnings are silenced for the call, so nothing a library prints reaches stderr; a refusal is a code only."""
    from maker_core.replay.v2.rehearsal import whitelisted
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = run(name, args)
            if name == "rehearse":
                whitelisted(result)
            if forbidden_keys(result):
                raise BundleError("rehearsal_output_forbidden_key")
    except Exception as exc:  # noqa: BLE001 - every failure becomes a code; no exception text is printed
        return None, refusal_code(exc)
    return result, None
