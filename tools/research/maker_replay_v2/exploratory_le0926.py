"""EXPLORATORY_NOT_COUNTED: the maker replay v2 shadow over captured UTC days 2026-09-23..2026-09-26 only.

Built per ``swarm-m/EXPLORATORY-SHADOW-HOST-SPEC.md`` (owner yes 2026-10-08, hazard grid 1.0 / 0.1 / 0.01).
Nothing this module writes is counted toward any gate, hurdle, ceiling, look, MG-1, desk study or v2
signature, and every file it writes is named ``EXPLORATORY-*``.

Guards
- **A (every subcommand, first statement, before any path is opened):** every day is canonical, inside
  2026-09-23..2026-09-26 and not ``export_gate.gated``; no input or output path component names a date
  2026-09-27 or later (dashed or compact); every output is new, has an existing parent, is named
  ``EXPLORATORY-*`` (files), and lies outside the repository, every ``--forbid-root``, every ``data`` tree and
  every nightly export root (a directory holding a ``*-ledger.jsonl``), and outside every input. Exit 2.
- **B (``verify``):** streams each sealed v0.2 bundle (two-pass ``open_stream_bundle``) and refuses any record or
  payload time at or after the cutoff, any untimestamped trade, settlement or plugin row, any settlement or
  settlement-ledger row for an event after 2026-09-26, and any descriptor for an event after 2026-09-28.
  Exit 4 on any breach.
- **C (``run``):** the sources raise on any record at or after the cutoff, and the engine refuses any instant,
  fill or settlement at or after it, independently of ``verify``. Exit 6.
- **Aggregate (and the run output):** an allowlist of exactly the keys and value shapes ``summarize`` emits.
  Any other key, any free-text string, any int or float of magnitude >= 1e12, any float with more than 12
  significant digits, any dict over 64 keys, any list over the schema's length or an output over 256 KiB is
  refused (exit 5). Run outputs round every float to 10 significant digits before the check. Exclusion
  reasons and dropped-day reasons are closed enums of the codes v2 and ``verify`` emit. The aggregate's sha
  fields are only hashes it computed itself from the files it read, plus the receipts' exporter module hash
  (pinned field set; the engine's ``selected_windows_sha256`` stays in the host-only run output).
- Band-day rows dated outside 2026-09-23..26 (a timer or decision at exactly 2026-09-27T00:00Z) are dropped
  from every summed field and counted in ``band_days_dropped_outside_window``; they never become a day key.
- Markouts on fills within one horizon of the cutoff read the last book before it (stale, biased toward 0);
  no book at or after the cutoff is ever read. Every run and aggregate carries that note.

The sealed hazard derivation over the three post-cutoff days is never imported or called here: the hazard comes
only from the declared grid. The inventory and time zones come only from the verified bundles' descriptors.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys

from maker_core.replay import export_gate
from maker_core.replay.bundle import KINDS as BUNDLE_KINDS
from maker_core.replay.bundle import BundleError, HOST_MAX_BYTES, HOST_MAX_RECORDS, HOST_MAX_SECONDS, Limits, timestamp

UTC = timezone.utc
LABEL = "EXPLORATORY_NOT_COUNTED"
PREFIX = "EXPLORATORY-"
EXPLORATORY_FIRST_UTC_DAY = date(2026, 9, 23)
EXPLORATORY_LAST_UTC_DAY = date(2026, 9, 26)
EXPLORATORY_CUTOFF = datetime(2026, 9, 27, tzinfo=UTC)  # exclusive
DESCRIPTOR_TARGET_LIMIT = date(2026, 9, 28)  # descriptors may name events up to here; outcomes may not
HAZARD_GRID = ("1.0", "0.1", "0.01")  # per minute; declared before any export, never fitted
POLICIES = ("informed-v0", "no_quote", "blind_re1", "clock_only")
FORBIDDEN_COMPONENT = re.compile(r"2026-(09-(2[7-9]|30)|1[0-2]-\d\d)")
FORBIDDEN_COMPACT = re.compile(r"(?<!\d)2026(09(2[7-9]|30)|1[0-2]\d\d)(?!\d)")
# Other spellings of a date after 2026-09-26: '.', '_', ' ' or '-' separators, two-digit years, month names.
FORBIDDEN_SPELLED = (
    re.compile(r"(?<![0-9])(20)?26[-._ ](09[-._ ](2[7-9]|30)|1[0-2][-._ ][0-3][0-9])(?![0-9])"),
    re.compile(r"(?<![0-9])((2[7-9]|30)[-._ ]09|[0-3][0-9][-._ ]1[0-2])[-._ ](20)?26(?![0-9])"),
    re.compile(r"(?i)(?<![a-z])(sep(t(ember)?)?[-._ ]?(2[7-9]|30)|oct(ober)?|nov(ember)?|dec(ember)?)"
               r"(?![a-z])[-._ ,]*[0-9]{0,2}[-._ ,]*(20)?26(?![0-9])"),
)
DEVICE_OR_UNC_PREFIXES = ("\\\\?\\", "\\\\.\\", "\\\\", "//", "\\??\\")
SUPPORT_TIME_KEYS = {"snapshots": "captured_at_utc", "source_rows": "captured_at_utc", "forecasts": "captured_at_utc",
                     "explanations": "captured_at_utc", "bulletins": "fetched_at",
                     "triggers": "current_captured_at_utc", "ledger_rows": "recorded_at_utc"}
PAYLOAD_TIME = {"book": ("as_of_utc",), "terms": ("as_of_utc",), "outcome_view": ("value", "as_of_utc")}
MAX_JSON_BYTES = 64 * 1024**2
AGGREGATE_MAX_BYTES = 256 * 1024
AGGREGATE_MAX_DICT = 64
MAX_ABS_NUMBER = 10**12
MAX_SIGNIFICANT_DIGITS = 12
OUTPUT_SIGNIFICANT_DIGITS = 10
FORBIDDEN_KEYS = frozenset({"condition_id", "condition_ids", "token_id", "token_ids", "asset_id", "asset_ids",
                            "trade_id", "trade_ids", "event_id", "event_ids", "event_slug", "slug", "slugs", "price",
                            "prices", "trade", "trades", "book", "books", "outcome_tokens", "market", "markets",
                            "fills_detail", "rows", "records"})  # named in refusals only; the allowlist decides
EXIT_REFUSED, EXIT_BREACH, EXIT_AGGREGATE_REFUSED, EXIT_GUARD_C = 2, 4, 5, 6
HOST_LIMITS = Limits(HOST_MAX_BYTES, HOST_MAX_RECORDS, HOST_MAX_SECONDS)


class Refusal(Exception):
    def __init__(self, code, exit_code=EXIT_REFUSED, **detail):
        super().__init__(code)
        self.code, self.exit_code, self.detail = code, exit_code, detail


class GuardCBreach(RuntimeError):
    """A record, instant, fill or settlement at or after the cutoff reached the driver (guard C)."""


def refuse(code, exit_code=EXIT_REFUSED, **detail):
    raise Refusal(code, exit_code, **detail)


# -- guard A ----------------------------------------------------------------------------------------------------
def repo_roots():
    roots = {Path(__file__).resolve().parents[3]}
    try:
        from weather import paths
        roots.update({Path(paths.REPO_ROOT).resolve(), Path(paths.DATA_ROOT).resolve()})
    except ImportError:  # pragma: no cover - the worktree always has weather.paths
        pass
    return roots


def check_day(value):
    try:
        day = export_gate.utc_day(value)
    except BundleError as exc:
        refuse(str(exc))
    if not EXPLORATORY_FIRST_UTC_DAY <= day <= EXPLORATORY_LAST_UTC_DAY:
        refuse("day_outside_exploratory_window", day=str(value))
    if export_gate.gated(day):
        refuse("panel_gated_day", day=str(value))
    return day


def _norm(path):
    return os.path.normcase(os.path.abspath(str(path)))


def inside(child, parent):
    child, parent = _norm(child), _norm(parent)
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:  # different drives
        return False


def check_prefix(path):
    """Refuse device, extended-length and UNC spellings: ``commonpath`` cannot compare them with drive paths."""
    raw = str(path)
    if raw.startswith(DEVICE_OR_UNC_PREFIXES) or raw.replace("/", "\\").startswith("\\\\"):
        refuse("path_device_or_unc_prefix")
    if os.path.splitdrive(os.path.abspath(raw))[0].startswith(("\\\\", "//")):
        refuse("path_device_or_unc_prefix")


def check_components(path):
    check_prefix(path)
    path = Path(path)
    for parts in (path.parts, Path(os.path.realpath(path)).parts):
        for part in parts:
            if (FORBIDDEN_COMPONENT.search(part) or FORBIDDEN_COMPACT.search(part)
                    or any(p.search(part) for p in FORBIDDEN_SPELLED)):
                refuse("forbidden_date_path_component", component=part)


def _ledger_root(directory):
    try:
        return any(p.is_file() for p in Path(directory).glob("*-ledger.jsonl"))
    except OSError:
        return True  # unreadable ancestor: fail closed


def check_output(path, inputs, forbid_roots, *, directory=False):
    path = Path(path)
    real = Path(os.path.realpath(path))
    if os.path.lexists(path):
        refuse("output_exists", output=path.name)
    if not real.parent.is_dir():
        refuse("output_parent_missing", output=path.name)
    if not path.name.startswith(PREFIX) and not directory:
        refuse("output_not_labelled_exploratory", output=path.name)
    for candidate in (path.absolute(), real):
        if any(part.casefold() == "data" for part in candidate.parts):
            refuse("output_inside_data_tree", output=path.name)
        for root in (*repo_roots(), *forbid_roots):
            if inside(candidate, root):
                refuse("output_inside_repository_or_forbidden_root", output=path.name)
        for ancestor in candidate.parents:
            if ancestor.is_dir() and _ledger_root(ancestor):
                refuse("output_inside_nightly_export_root", output=path.name)
        for source in inputs:
            if inside(candidate, source) or inside(source, candidate):
                refuse("output_overlaps_input", output=path.name)


def guard_a(days, *, inputs, outputs, directories=(), forbid_roots=(), require_days=True):
    """Guard A: pure checks of names and metadata; nothing is opened or created."""
    if require_days and not days:
        refuse("days_required")
    parsed = []
    for value in days or ():
        day = check_day(value)
        if day in parsed:
            refuse("duplicate_day", day=str(value))
        parsed.append(day)
    inputs = [Path(p) for p in inputs if p is not None]
    forbid = [Path(p) for p in forbid_roots or ()]
    for root in forbid:
        check_prefix(root)
    for path in (*inputs, *[p for p in (*outputs, *directories) if p is not None]):
        check_components(path)
    for source in inputs:
        if any(part.casefold() == "data" for part in Path(os.path.realpath(source)).parts):
            refuse("input_inside_data_tree")
        if any(inside(source, root) for root in repo_roots()):
            refuse("input_inside_repository")
    for out in outputs:
        if out is not None:
            check_output(out, inputs, forbid)
    for out in directories:
        if out is not None:
            check_output(out, inputs, forbid, directory=True)
    return sorted(parsed)


# -- small IO helpers -------------------------------------------------------------------------------------------
def read_json(path, cap=MAX_JSON_BYTES):
    path = Path(path)
    with path.open("rb") as handle:
        raw = handle.read(cap + 1)
    if len(raw) > cap:
        refuse("json_input_too_large", name=path.name)
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def to_plain(value):
    if isinstance(value, dict):
        return {str(k): to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(v) for v in value]
    if isinstance(value, Decimal):
        return float(value) if value.is_finite() else None  # aggregates: no long digit strings
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and not (value == value and abs(value) != float("inf")):
        return None
    return value


def write_json(path, value):
    raw = (json.dumps(to_plain(value), sort_keys=True, indent=1) + "\n").encode()
    with Path(path).open("xb") as handle:
        handle.write(raw)
    return hashlib.sha256(raw).hexdigest()


def _time(value):
    """A UTC timestamp, or None when missing or unparseable (the caller records the breach)."""
    if value is None or value == "":
        return None
    try:
        return timestamp(value if isinstance(value, str) else str(value))
    except (BundleError, ValueError, TypeError):
        return None


def _path_get(mapping, keys):
    for key in keys:
        if not hasattr(mapping, "get"):
            return None
        mapping = mapping.get(key)
    return mapping


def event_target(slug):
    """(market_id, target date) of a built-in event slug, or None."""
    from weather.market.maker_plugin.inputs import event_identity
    try:
        spec, target = event_identity(slug)
    except (ValueError, TypeError, AttributeError):
        return None
    return spec.id, target


def builtin_markets():
    from weather.market.maker_replay_universe import registered_time_zones
    return registered_time_zones()


def open_bundle(path):
    from maker_core.replay.bundle_v02 import FORMAT_V02, open_stream_bundle
    bundle = open_stream_bundle(Path(path), limits=HOST_LIMITS)
    if bundle.format != FORMAT_V02:
        raise BundleError("exploratory_requires_bundle_v02")
    return bundle


def descriptor_view(bundle):
    """The bundle restricted to its descriptor stream (inventory and targets come from descriptors only)."""
    return replace(bundle, streams=tuple(s for s in bundle.streams if s.name == "descriptor.jsonl"))


# -- guard B: verify --------------------------------------------------------------------------------------------
class _Stats:
    def __init__(self):
        self.kinds, self.breaches = {}, {}

    def see(self, kind, captured, event=None):
        k = self.kinds.setdefault(kind, dict(count=0, captured_min=None, captured_max=None,
                                             event_min=None, event_max=None))
        k["count"] += 1
        for name, value in (("captured", captured), ("event", event)):
            if value is None:
                continue
            if k[name + "_min"] is None or value < k[name + "_min"]:
                k[name + "_min"] = value
            if k[name + "_max"] is None or value > k[name + "_max"]:
                k[name + "_max"] = value

    def breach(self, code, kind):
        key = (code, kind)
        self.breaches[key] = self.breaches.get(key, 0) + 1


def _receipt_time_breaches(value, path=""):
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            name = f"{path}.{key}" if path else str(key)
            if re.search(r"untimestamp|missing_time|no_time|time_missing", str(key), re.I):
                if isinstance(item, (int, float)) and not isinstance(item, bool) and item:
                    found.append(name)
            found.extend(_receipt_time_breaches(item, name))
    elif isinstance(value, list):
        for item in value:
            found.extend(_receipt_time_breaches(item, path))
    return found


def descriptor_targets(bundle, stats=None):
    """condition_id -> (market_id, target) from the descriptor stream, with descriptor breaches."""
    from maker_core.replay.payloads import market_descriptor
    markets = {c.condition_id: c.market_id for c in bundle.conditions}
    targets, count = {}, 0
    for record in descriptor_view(bundle).records():
        if record.kind != "descriptor":
            if stats is not None:
                stats.breach("non_descriptor_in_descriptor_stream", record.kind)
            continue
        count += 1
        try:
            event = market_descriptor(record.payload["market"]).event_id
        except (KeyError, TypeError, ValueError):
            event = None
        identity = event_target(event)
        if identity is None:
            if stats is not None:
                stats.breach("descriptor_unregistered_event", "descriptor")
            continue
        if identity[1] > DESCRIPTOR_TARGET_LIMIT and stats is not None:
            stats.breach("descriptor_target_after_limit", "descriptor")
        if identity[0] != markets.get(record.condition_id) and stats is not None:
            stats.breach("descriptor_market_mismatch", "descriptor")
        if targets.setdefault(record.condition_id, identity) != identity and stats is not None:
            stats.breach("descriptor_target_changed", "descriptor")
    return targets, count


def verify_record(record, stats, targets, start, end):
    kind, captured = record.kind, record.captured_at
    if captured >= EXPLORATORY_CUTOFF:
        stats.breach("record_at_or_after_cutoff", kind)
    if not start <= captured < end:
        stats.breach("record_outside_bundle_day", kind)
    payload = record.payload
    event = None
    if kind == "trade":
        event = _time(payload.get("traded_at_utc"))
        if event is None:
            stats.breach("trade_untimestamped", kind)
        elif event >= EXPLORATORY_CUTOFF:
            stats.breach("trade_at_or_after_cutoff", kind)
    elif kind == "settlement":
        event = _time(payload.get("as_of_utc"))
        if event is None:
            stats.breach("settlement_untimestamped", kind)
        elif event >= EXPLORATORY_CUTOFF:
            stats.breach("settlement_at_or_after_cutoff", kind)
        identity = targets.get(record.condition_id)
        if identity is None:
            stats.breach("settlement_without_descriptor", kind)
        elif identity[1] > EXPLORATORY_LAST_UTC_DAY:
            stats.breach("settlement_for_event_after_last_day", kind)
    elif kind == "plugin_input":
        event = _time(payload.get("original_captured_at"))
        if event is None:
            stats.breach("plugin_input_untimestamped", kind)
        elif event >= EXPLORATORY_CUTOFF:
            stats.breach("plugin_input_at_or_after_cutoff", kind)
        source, row = payload.get("source"), payload.get("record")
        key = SUPPORT_TIME_KEYS.get(source)
        if key is None:
            stats.breach("plugin_input_unknown_source", kind)
        else:
            inner = _time(row.get(key)) if hasattr(row, "get") else None
            if inner is None:
                stats.breach("plugin_record_untimestamped", kind)
            elif inner >= EXPLORATORY_CUTOFF:
                stats.breach("plugin_record_at_or_after_cutoff", kind)
            if source == "ledger_rows":
                identity = event_target(row.get("event_slug")) if hasattr(row, "get") else None
                if identity is None:
                    stats.breach("ledger_row_unidentified", kind)
                elif identity[1] > EXPLORATORY_LAST_UTC_DAY:
                    stats.breach("ledger_row_for_event_after_last_day", kind)
    elif kind in PAYLOAD_TIME:
        event = _time(_path_get(payload, PAYLOAD_TIME[kind]))
        if event is None:
            stats.breach(kind + "_untimestamped", kind)
        elif event >= EXPLORATORY_CUTOFF:
            stats.breach(kind + "_at_or_after_cutoff", kind)
    elif kind == "coverage":
        event = _time(payload.get("valid_until_utc"))
    elif kind not in ("descriptor", "info_event"):
        stats.breach("unknown_record_kind", "other")
    stats.see(kind, captured, event)


DROP_RECEIPT_MISSING, DROP_RECEIPT_NOT_SEALED = "receipt_missing", "receipt_not_sealed"
DROP_RECEIPT_DAY_MISMATCH, DROP_NOT_TRAILING = "receipt_day_mismatch", "not_in_trailing_contiguous_block"
DROP_REASONS = frozenset({DROP_RECEIPT_MISSING, DROP_RECEIPT_NOT_SEALED, DROP_RECEIPT_DAY_MISMATCH, DROP_NOT_TRAILING})


def verify_day(root, day):
    """(entry, dropped_reason) for one day under the export root."""
    folder = Path(root) / day.isoformat()
    receipt_path = folder / "receipt.json"
    if not receipt_path.is_file():
        return None, DROP_RECEIPT_MISSING
    receipt, receipt_sha = read_json(receipt_path, 16 * 1024**2)
    if not isinstance(receipt, dict) or receipt.get("status") != "SEALED":
        return None, DROP_RECEIPT_NOT_SEALED
    if receipt.get("day") != day.isoformat():
        return None, DROP_RECEIPT_DAY_MISMATCH
    stats = _Stats()
    for name in _receipt_time_breaches(receipt):
        stats.breach("exporter_untimestamped_coverage_nonzero", "receipt")
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    end = start + timedelta(days=1)
    try:
        bundle = open_bundle(folder / "bundle")
    except (BundleError, OSError, ValueError) as exc:
        stats.breach("bundle_unreadable:" + str(exc)[:60], "bundle")
        return dict(stats=stats, receipt_sha256=receipt_sha, module_sha256=receipt.get("module_sha256"),
                    input_hashes={}, sealed_at=None), None
    if bundle.day != day:
        stats.breach("bundle_day_mismatch", "bundle")
    if bundle.sealed_at != end or bundle.sealed_at > EXPLORATORY_CUTOFF:
        stats.breach("sealed_at_not_day_end", "bundle")
    registered = builtin_markets()
    if any(c.market_id not in registered for c in bundle.conditions):
        stats.breach("condition_market_not_builtin", "bundle")
    targets, described = descriptor_targets(bundle, stats)
    seen_descriptors = 0
    try:
        for record in bundle.records():
            seen_descriptors += record.kind == "descriptor"
            verify_record(record, stats, targets, start, end)
    except BundleError as exc:
        stats.breach("bundle_stream_refused:" + str(exc)[:60], "bundle")
    if seen_descriptors != described:
        stats.breach("descriptor_outside_descriptor_stream", "descriptor")
    return dict(stats=stats, receipt_sha256=receipt_sha, module_sha256=receipt.get("module_sha256"),
                input_hashes=dict(bundle.input_hashes), sealed_at=bundle.sealed_at), None


def trailing_block(days):
    block = []
    for day in sorted(days, reverse=True):
        if block and block[-1] - day != timedelta(days=1):
            break
        block.append(day)
    return sorted(block)


def check_pin(pin):
    if pin is not None and re.fullmatch(r"[0-9a-f]{40}", pin) is None:
        refuse("pin_not_40_hex")


def cmd_verify(args):
    days = guard_a(args.day, inputs=[args.bundle_root], outputs=[args.out, args.result],
                   forbid_roots=args.forbid_root)
    check_pin(args.pin)
    per_day, dropped, breaches = {}, [], []
    for day in days:
        entry, reason = verify_day(args.bundle_root, day)
        if entry is None:
            dropped.append(dict(day=day.isoformat(), reason=reason))
            continue
        stats = entry.pop("stats")
        entry["kinds"] = stats.kinds
        per_day[day.isoformat()] = entry
        breaches.extend(dict(day=day.isoformat(), code=code, kind=kind, count=n)
                        for (code, kind), n in sorted(stats.breaches.items()))
    sealed = [date.fromisoformat(d) for d in per_day]
    used = trailing_block(sealed)
    for day in sorted(set(sealed) - set(used)):
        dropped.append(dict(day=day.isoformat(), reason=DROP_NOT_TRAILING))
    status = "BREACH" if breaches else "PASS" if used else "NO_DAYS"
    result = dict(label=LABEL, counted=False, cutoff_utc_exclusive=EXPLORATORY_CUTOFF, status=status,
                  days_requested=[d.isoformat() for d in days], days_used=[d.isoformat() for d in used],
                  days_dropped=sorted(dropped, key=lambda d: d["day"]), per_day=per_day, breaches=breaches)
    sha = write_json(args.out, result)
    code = EXIT_BREACH if breaches else (0 if used else EXIT_REFUSED)
    return code, dict(status=status, out_sha256=sha, days_used=result["days_used"], breaches=len(breaches))


# -- guard C: the driver ----------------------------------------------------------------------------------------
def _record_cutoff_code(record):
    if record.captured_at >= EXPLORATORY_CUTOFF:
        return "record_at_or_after_cutoff"
    payload = record.payload
    if record.kind == "trade":
        traded = _time(payload.get("traded_at_utc"))
        if traded is None or traded >= EXPLORATORY_CUTOFF:
            return "trade_untimestamped_or_at_or_after_cutoff"
    if record.kind == "settlement":
        as_of = _time(payload.get("as_of_utc"))
        if as_of is None or as_of >= EXPLORATORY_CUTOFF:
            return "settlement_untimestamped_or_at_or_after_cutoff"
    if record.kind == "plugin_input":
        at = _time(payload.get("original_captured_at"))
        if at is None or at >= EXPLORATORY_CUTOFF:
            return "plugin_input_untimestamped_or_at_or_after_cutoff"
    return None


def guarded_records(records):
    for record in records:
        code = _record_cutoff_code(record)
        if code is not None:
            raise GuardCBreach(code)
        yield record


def guarded_source(source):
    """A ``DaySource`` whose every record pass raises on a record at or after the cutoff (guard C)."""
    from maker_core.replay.v2.lockstep import DaySource
    if not EXPLORATORY_FIRST_UTC_DAY <= source.plan.day <= EXPLORATORY_LAST_UTC_DAY:
        raise GuardCBreach("source_day_outside_exploratory_window")
    inner = source.records
    return DaySource(source.plan, lambda: guarded_records(inner()))


def _check_fills(fills):
    for fill in fills:
        if fill.at >= EXPLORATORY_CUTOFF or fill.traded_at >= EXPLORATORY_CUTOFF:
            raise GuardCBreach("fill_at_or_after_cutoff")


def guarded_engine_class():
    from maker_core.replay.v2.engine import EngineV2

    class GuardedEngine(EngineV2):
        """``EngineV2`` that refuses any instant, fill or settlement at or after the cutoff."""

        def instant(self, at, batch):
            if at >= EXPLORATORY_CUTOFF:
                raise GuardCBreach("instant_at_or_after_cutoff")
            before = len(self.fills)
            result = super().instant(at, batch)
            _check_fills(self.fills[before:])
            return result

        def finish(self):
            result = super().finish()
            _check_fills(self.fills)
            for fact in self.settlements.values():
                if fact.as_of_utc >= EXPLORATORY_CUTOFF:
                    raise GuardCBreach("settlement_at_or_after_cutoff")
            return result

    return GuardedEngine


def inventory_and_zones(bundles):
    """Universe rows and market zones from the <= 09-26 bundles' descriptor streams only."""
    from maker_core.replay.execution_manifest import market_time_zones
    rows, views = {}, []
    registered = builtin_markets()
    for bundle in bundles:
        if not EXPLORATORY_FIRST_UTC_DAY <= bundle.day <= EXPLORATORY_LAST_UTC_DAY:
            refuse("inventory_bundle_outside_exploratory_window")
        from maker_core.replay.payloads import market_descriptor
        markets = {c.condition_id: c.market_id for c in bundle.conditions}
        descriptors = []
        for record in descriptor_view(bundle).records():
            if record.kind != "descriptor":
                continue
            descriptor = market_descriptor(record.payload["market"])
            identity = event_target(descriptor.event_id)
            if identity is None or identity[0] != markets.get(record.condition_id):
                refuse("inventory_descriptor_not_builtin_or_mismatched", EXIT_BREACH)
            if identity[1] > DESCRIPTOR_TARGET_LIMIT:
                refuse("inventory_descriptor_target_after_limit", EXIT_BREACH)
            row = dict(condition_id=record.condition_id, market_id=identity[0], domain_id=descriptor.domain_id,
                       target_date=identity[1].isoformat(), local_timezone=registered[identity[0]])
            if rows.setdefault(record.condition_id, row) != row:
                refuse("inventory_binding_changed", EXIT_BREACH)
            descriptors.append(record)
        views.append(_InventoryView(bundle.conditions, descriptors))
    inventory = [rows[cid] for cid in sorted(rows)]
    if any(r["market_id"] not in registered for r in inventory):
        refuse("inventory_market_not_builtin", EXIT_BREACH)
    zones = market_time_zones(views, inventory, registered=registered)
    return inventory, zones


class _InventoryView:
    """What ``execution_manifest._inventory`` reads: conditions and an iterable of (descriptor) records."""

    def __init__(self, conditions, records):
        self.conditions, self.records = conditions, records


def _quantiles(values):
    if not values:
        return dict(n=0, mean=None, q1=None, median=None, q3=None)
    values = sorted(values)
    if len(values) == 1:
        q = (values[0],) * 3
    else:
        q = statistics.quantiles(values, n=4, method="inclusive")
    return dict(n=len(values), mean=sum(values) / len(values), q1=q[0], median=q[1], q3=q[2])


def _window_rows(rows):
    """(rows dated 2026-09-23..26, count of others). A QUOTE or timer at exactly the cutoff instant would
    otherwise open a 2026-09-27 band-day row; it carries no pre-cutoff information and is dropped, coded."""
    kept = [r for r in rows if _window_day(r["date"])]
    return kept, len(rows) - len(kept)


def summarize(run):
    """Per fill bound x policy: counts and sums only (no identifiers, prices or series)."""
    from maker_core.replay.score import HORIZONS
    from maker_core.replay.v2.score import US, us
    out = {}
    for bound, policies in run.passes.items():
        out[bound] = {}
        for policy, p in policies.items():
            rows, outside = _window_rows(p.band_days(run.books, run.markets))
            engine = p.engine
            covered = sum((Decimal(r["covered_seconds"]) for r in rows), Decimal(0))
            pulled = sum((Decimal(r["pulled_seconds"]) for r in rows), Decimal(0))
            markouts = {h: [] for h in ("0s", *HORIZONS)}
            notional = shares = settled_pnl = Decimal(0)
            settled = 0
            for fill in engine.fills:
                notional += fill.price * fill.size
                shares += fill.size
                for name in markouts:
                    offset = 0 if name == "0s" else HORIZONS[name] * US
                    mark = run.books.mark(fill.condition_id, fill.outcome, us(fill.at) + offset)
                    if mark is not None:
                        markouts[name].append(float(Decimal(str(mark)) - fill.price))
                fact = engine.settlements.get(fill.condition_id)
                if fact is not None:
                    payout = Decimal(str(fact.p_yes if fill.outcome == "YES" else 1 - fact.p_yes))
                    settled += 1
                    settled_pnl += (payout - fill.price) * fill.size
            open_lots = [(cid, lot) for cid, state in engine.states.items() for lot in getattr(state, "lots", ())]
            per_day = {}
            for r in rows:
                d = per_day.setdefault(r["date"], dict(band_days=0, band_days_quoted=0, fills=0, quotes=0))
                d["band_days"] += 1
                d["band_days_quoted"] += int(bool(r["quotes"]))
                d["fills"] += r["fills"]
                d["quotes"] += r["quotes"]
            net = [r["modeled_net_k1"] for r in rows if r["modeled_net_k1"] is not None]
            summary = engine.summary()
            out[bound][policy] = dict(
                decisions=engine.decision_count, band_days=len(rows),
                band_days_quoted=sum(1 for r in rows if r["quotes"]),
                quoted_fraction=(1 - pulled / covered) if covered else None, covered_seconds=covered,
                fills=len(engine.fills), filled_shares=shares, filled_notional=notional,
                markout_per_share={h: _quantiles(v) for h, v in markouts.items()},
                markout_missing={h: len(engine.fills) - len(v) for h, v in markouts.items()},
                spread_captured_per_share=_quantiles(markouts["0s"])["mean"],
                settled_subset=dict(fills=settled, net_pnl=settled_pnl,
                                    band_days_modeled_net_k1=len(net), modeled_net_k1=sum(net, Decimal(0))),
                unsettled_at_cutoff=dict(conditions=len({cid for cid, _ in open_lots}), lots=len(open_lots),
                                         exposure=sum((lot.price * lot.size for _, lot in open_lots), Decimal(0))),
                rewards=dict(k1=sum((r["reward_k1"] for r in rows), Decimal(0)),
                             k05=sum((r["reward_k05"] for r in rows), Decimal(0)),
                             nominal_rebate=sum((r["nominal_rebate"] for r in rows), Decimal(0))),
                exclusions=summary["exclusions"], final_cash=engine.cash, per_day=per_day,
                band_days_dropped_outside_window=outside)
        out[bound]["matched_clock"] = run.matches.get(bound)
    return out


def execute(sources, zones, hazard):
    """Guard C around ``run_passes``: guarded sources, the guarded engine, fresh state, declared hazard."""
    from maker_core.replay.v2.kernel import V2Config
    from maker_core.replay.v2.pipeline import run_passes
    if str(hazard) not in HAZARD_GRID:
        refuse("hazard_not_in_declared_grid")
    sources = [guarded_source(s) for s in sources]
    run = run_passes(sources, V2Config(hazard_per_minute=float(hazard)), time_zones=zones,
                     engine=guarded_engine_class())
    return summarize(run)


def cmd_run(args):
    days = guard_a(args.day, inputs=[args.bundle_root, args.verify], outputs=[args.result],
                   directories=[args.out], forbid_roots=args.forbid_root)
    check_pin(args.pin)
    if args.hazard_per_minute not in HAZARD_GRID:
        refuse("hazard_not_in_declared_grid")
    verified, verify_sha = read_json(args.verify)
    if (verified.get("label") != LABEL or verified.get("status") != "PASS"
            or verified.get("days_used") != [d.isoformat() for d in days]):
        refuse("verify_not_pass_for_these_days")
    bundles = []
    for day in days:
        bundle = open_bundle(Path(args.bundle_root) / day.isoformat() / "bundle")
        expected = verified["per_day"][day.isoformat()]["input_hashes"]
        if bundle.day != day or dict(bundle.input_hashes) != expected:
            refuse("input_changed_since_verify", EXIT_BREACH, day=day.isoformat())
        bundles.append(bundle)
    from maker_core.replay.v2.lockstep import stream_source
    _, zones = inventory_and_zones(bundles)
    summary = execute([stream_source(b) for b in bundles], zones, args.hazard_per_minute)
    result = dict(label=LABEL, counted=False, cutoff_utc_exclusive=EXPLORATORY_CUTOFF,
                  hazard_per_minute=args.hazard_per_minute, hazard_grid=list(HAZARD_GRID), pin=args.pin,
                  verify_sha256=verify_sha, days_used=[d.isoformat() for d in days], markout_note=MARKOUT_NOTE,
                  market_count=len(zones), results=summary)
    result = round_numbers(to_plain(result))
    check_schema(result, RUN_SCHEMA)
    os.mkdir(args.out)
    sha = write_json(Path(args.out) / (PREFIX + "run.json"), result)
    return 0, dict(status="RUN", out_sha256=sha, hazard_per_minute=args.hazard_per_minute)


# -- aggregate allowlist ---------------------------------------------------------------------------------------
CUTOFF_TEXT = EXPLORATORY_CUTOFF.isoformat()
HEADING = "exploratory, not counted, <= 2026-09-26, partial settlement"
MARKOUT_NOTE = ("markouts on fills within one horizon of the cutoff use the last book before 2026-09-27T00:00Z "
                "(stale, biased toward 0); no book at or after the cutoff is read")
MATCH_INTERPRETATION = "ex-post exposure-matched clock control; no return optimization"
BOUND_KEYS = ("strictly_through", "at_price")  # == maker_core.replay.fill_model.BOUNDS (tested)
HORIZON_KEYS = ("0s", "1m", "5m", "30m")  # "0s" plus maker_core.replay.score.HORIZONS (tested)

# The v2 exclusion reasons: kernel ``INVALID_<KIND>`` per bundle record kind, the trade and print checks, and
# blind RE-1's transport assumption (tests tie this to the emitting sources).
EXCLUSION_CODES = frozenset({"INVALID_" + k.upper() for k in BUNDLE_KINDS}
                            | {"INVALID_TRADE", "PRINT_PREDATES_ORDER", "RE1_TRANSPORT_ASSUMED"})

_N, _I = ("num",), ("int",)
_SHA, _PIN = ("re", re.compile(r"[0-9a-f]{64}")), ("re", re.compile(r"[0-9a-f]{40}"))
_DAY = ("day",)
_HAZARD = ("enum", frozenset(HAZARD_GRID))
_Q = ("dict", {"n": _I, "mean": _N, "q1": _N, "median": _N, "q3": _N})
_POLICY = ("dict", {
    "decisions": _I, "band_days": _I, "band_days_quoted": _I, "quoted_fraction": _N, "covered_seconds": _N,
    "fills": _I, "filled_shares": _N, "filled_notional": _N,
    "markout_per_share": ("dict", {h: _Q for h in HORIZON_KEYS}),
    "markout_missing": ("dict", {h: _I for h in HORIZON_KEYS}),
    "spread_captured_per_share": _N,
    "settled_subset": ("dict", {"fills": _I, "net_pnl": _N, "band_days_modeled_net_k1": _I, "modeled_net_k1": _N}),
    "unsettled_at_cutoff": ("dict", {"conditions": _I, "lots": _I, "exposure": _N}),
    "rewards": ("dict", {"k1": _N, "k05": _N, "nominal_rebate": _N}),
    "exclusions": ("map", ("enum", EXCLUSION_CODES), _I, len(EXCLUSION_CODES)),
    "final_cash": _N,
    "per_day": ("map", _DAY, ("dict", {"band_days": _I, "band_days_quoted": _I, "fills": _I, "quotes": _I}), 4),
    "band_days_dropped_outside_window": _I,
})
_MATCH_FIELDS = {
    "status": ("enum", frozenset({"MATCHED", "UNMATCHED"})), "target": _N, "actual": _N, "tolerance": _N,
    "absolute_error": _N, "attempts": _I, "calendar_prefix_fraction": _N, "selected_windows": _I,
    "interpretation": ("enum", frozenset({MATCH_INTERPRETATION})),
}
# The engine's window digest cannot be re-derived by the aggregate, so it stays in the host-only run output.
_MATCH = ("dict", {**_MATCH_FIELDS, "selected_windows_sha256": _SHA})
_MATCH_AGGREGATE = ("dict", _MATCH_FIELDS)
_RESULTS = ("dict", {b: ("dict", {**{p: _POLICY for p in POLICIES}, "matched_clock": _MATCH}) for b in BOUND_KEYS})
_RESULTS_AGGREGATE = ("dict", {b: ("dict", {**{p: _POLICY for p in POLICIES}, "matched_clock": _MATCH_AGGREGATE})
                               for b in BOUND_KEYS})
_COMMON = {"label": ("const", LABEL), "counted": ("const", False), "cutoff_utc_exclusive": ("const", CUTOFF_TEXT),
           "pin": _PIN, "verify_sha256": _SHA, "days_used": ("list", _DAY, 4),
           "hazard_grid": ("list", _HAZARD, len(HAZARD_GRID)), "markout_note": ("const", MARKOUT_NOTE)}
RUN_SCHEMA = ("dict", {**_COMMON, "hazard_per_minute": _HAZARD, "market_count": _I, "results": _RESULTS})
AGGREGATE_SCHEMA = ("dict", {
    **_COMMON, "module_sha256": _SHA, "module_sha256_distinct": _I, "input_manifest_sha256": _SHA,
    "days_dropped": ("list", ("dict", {"day": _DAY, "reason": ("enum", DROP_REASONS)}), 4),
    "hazards_missing": ("list", _HAZARD, len(HAZARD_GRID)),
    "runs": ("list", ("dict", {"hazard_per_minute": _HAZARD, "run_sha256": _SHA}), len(HAZARD_GRID)),
    "heading": ("const", HEADING), "results": ("dict", {"h" + h: _RESULTS_AGGREGATE for h in HAZARD_GRID}),
})
# Every *_sha256 in the aggregate: (field path, where its value comes from). Checked after the schema.
AGGREGATE_SHA_FIELDS = ("verify_sha256", "input_manifest_sha256", "module_sha256", "runs[].run_sha256")


def _aggregate_refuse(code, where):
    refuse(code, EXIT_AGGREGATE_REFUSED, where=where[-80:])


def _number_ok(value, integer):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return abs(value) < MAX_ABS_NUMBER
    if integer or not isinstance(value, float) or not math.isfinite(value) or abs(value) >= MAX_ABS_NUMBER:
        return False
    mantissa = repr(abs(value)).split("e")[0].replace(".", "").lstrip("0").rstrip("0")
    return len(mantissa) <= MAX_SIGNIFICANT_DIGITS


def _window_day(value):
    if not isinstance(value, str) or re.fullmatch(r"2026-09-2[3-6]", value) is None:
        return False
    return True


def check_schema(value, node, where="$"):
    """Refuse (exit 5) anything that is not exactly a shape ``summarize`` emits; ``None`` is allowed for leaves."""
    kind = node[0]
    if kind == "const":
        if type(value) is not type(node[1]) or value != node[1]:
            _aggregate_refuse("aggregate_value_not_allowed", where)
        return
    if value is None:
        return
    if kind in ("num", "int"):
        if not _number_ok(value, kind == "int"):
            _aggregate_refuse("aggregate_number_refused", where)
    elif kind == "enum":
        if not isinstance(value, str) or value not in node[1]:
            _aggregate_refuse("aggregate_value_not_allowed", where)
    elif kind == "re":
        if not isinstance(value, str) or node[1].fullmatch(value) is None:
            _aggregate_refuse("aggregate_value_not_allowed", where)
    elif kind == "day":
        if not _window_day(value):
            _aggregate_refuse("aggregate_value_not_allowed", where)
    elif kind == "list":
        if not isinstance(value, list):
            _aggregate_refuse("aggregate_value_not_allowed", where)
        if len(value) > node[2]:
            _aggregate_refuse("aggregate_series_refused", where)
        for i, item in enumerate(value):
            check_schema(item, node[1], f"{where}[{i}]")
    elif kind in ("dict", "map"):
        if not isinstance(value, dict):
            _aggregate_refuse("aggregate_value_not_allowed", where)
        limit = node[3] if kind == "map" else AGGREGATE_MAX_DICT
        if len(value) > min(limit, AGGREGATE_MAX_DICT):
            _aggregate_refuse("aggregate_dict_too_large", where)
        for key, item in value.items():
            if kind == "dict":
                if key not in node[1]:
                    forbidden = isinstance(key, str) and key.casefold() in FORBIDDEN_KEYS
                    _aggregate_refuse("aggregate_forbidden_key" if forbidden else "aggregate_key_not_allowed", where)
                check_schema(item, node[1][key], f"{where}.{key}")
            else:
                try:
                    check_schema(key, node[1], where)
                except Refusal:
                    _aggregate_refuse("aggregate_key_not_allowed", where)
                check_schema(item, node[2], f"{where}.{key}")
    else:  # pragma: no cover - schema typo
        raise AssertionError(kind)


def _strip_window_digests(results):
    if not isinstance(results, dict):
        return results
    out = {}
    for bound, policies in results.items():
        out[bound] = policies
        if isinstance(policies, dict) and isinstance(policies.get("matched_clock"), dict):
            out[bound] = dict(policies, matched_clock={k: v for k, v in policies["matched_clock"].items()
                                                       if k != "selected_windows_sha256"})
    return out


def _check_aggregate_shas(result, verify_sha, manifest_sha, run_shas, modules):
    """Each sha field must be a hash this process computed from a file it read (or the receipts' module hash)."""
    expected_runs = [dict(hazard_per_minute=h, run_sha256=run_shas[h]) for h in HAZARD_GRID if h in run_shas]
    module = modules[0] if len(modules) == 1 else None
    if (result.get("verify_sha256") != verify_sha or result.get("input_manifest_sha256") != manifest_sha
            or result.get("runs") != expected_runs or result.get("module_sha256") != module):
        _aggregate_refuse("aggregate_sha_not_bound", "$")


def round_numbers(value):
    """Every float to ``OUTPUT_SIGNIFICANT_DIGITS`` significant digits (the allowlist refuses longer ones)."""
    if isinstance(value, dict):
        return {k: round_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [round_numbers(v) for v in value]
    if isinstance(value, float) and math.isfinite(value):
        return float(f"{value:.{OUTPUT_SIGNIFICANT_DIGITS}g}")
    return value


def cmd_aggregate(args):
    guard_a([], inputs=[args.run_root, args.verify, args.input_manifest], outputs=[args.out, args.result],
            forbid_roots=args.forbid_root, require_days=False)
    check_pin(args.pin)
    verified, verify_sha = read_json(args.verify)
    if verified.get("label") != LABEL or verified.get("status") != "PASS":
        refuse("verify_not_pass")
    days = [check_day(d) for d in verified.get("days_used") or ()]
    if not days:
        refuse("days_required")
    _, manifest_sha = read_json(args.input_manifest)
    runs = {}
    for path in sorted(Path(args.run_root).glob("*/" + PREFIX + "run.json")):
        check_components(path)
        value, sha = read_json(path)
        if not isinstance(value, dict):
            refuse("run_output_inconsistent")
        hazard = value.get("hazard_per_minute")
        if (value.get("label") != LABEL or value.get("counted") is not False or hazard not in HAZARD_GRID
                or value.get("days_used") != [d.isoformat() for d in days] or hazard in runs
                or value.get("verify_sha256") != verify_sha):
            refuse("run_output_inconsistent")
        runs[hazard] = (value, sha)
    if not runs:
        refuse("no_run_outputs")
    modules = sorted({e.get("module_sha256") for e in verified["per_day"].values() if e.get("module_sha256")})
    result = dict(label=LABEL, counted=False, cutoff_utc_exclusive=EXPLORATORY_CUTOFF.isoformat(),
                  pin=args.pin, module_sha256=modules[0] if len(modules) == 1 else None,
                  module_sha256_distinct=len(modules), input_manifest_sha256=manifest_sha, verify_sha256=verify_sha,
                  days_used=[d.isoformat() for d in days],
                  days_dropped=[dict(day=d["day"], reason=d["reason"]) for d in verified.get("days_dropped", ())],
                  hazard_grid=list(HAZARD_GRID), hazards_missing=[h for h in HAZARD_GRID if h not in runs],
                  runs=[dict(hazard_per_minute=h, run_sha256=runs[h][1]) for h in HAZARD_GRID if h in runs],
                  heading=HEADING, markout_note=MARKOUT_NOTE,
                  results={"h" + h: _strip_window_digests(runs[h][0]["results"]) for h in HAZARD_GRID if h in runs})
    result = to_plain(result)
    check_schema(result, AGGREGATE_SCHEMA)
    _check_aggregate_shas(result, verify_sha, manifest_sha, {h: v[1] for h, v in runs.items()}, modules)
    raw = (json.dumps(result, sort_keys=True, indent=1) + "\n").encode()
    if len(raw) > AGGREGATE_MAX_BYTES:
        refuse("aggregate_too_large", EXIT_AGGREGATE_REFUSED)
    with Path(args.out).open("xb") as handle:
        handle.write(raw)
    return 0, dict(status="AGGREGATED", out_sha256=hashlib.sha256(raw).hexdigest(), hazards=sorted(runs))


# -- CLI --------------------------------------------------------------------------------------------------------
def parser():
    p = argparse.ArgumentParser(prog="exploratory_le0926", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--result", help="also write the one-line result JSON here (EXPLORATORY-*)")
    common.add_argument("--forbid-root", action="append", default=[],
                        help="a tree no output may enter (the production checkout on the host)")
    common.add_argument("--pin", default=None, help="the 40-hex pinned tip, recorded in outputs")
    v = sub.add_parser("verify", parents=[common])
    v.add_argument("--bundle-root", required=True)
    v.add_argument("--day", nargs="+", required=True)
    v.add_argument("--out", required=True)
    r = sub.add_parser("run", parents=[common])
    r.add_argument("--bundle-root", required=True)
    r.add_argument("--day", nargs="+", required=True)
    r.add_argument("--hazard-per-minute", required=True)
    r.add_argument("--verify", required=True)
    r.add_argument("--out", required=True)
    a = sub.add_parser("aggregate", parents=[common])
    a.add_argument("--run-root", required=True)
    a.add_argument("--verify", required=True)
    a.add_argument("--input-manifest", required=True)
    a.add_argument("--out", required=True)
    return p


COMMANDS = {"verify": cmd_verify, "run": cmd_run, "aggregate": cmd_aggregate}


def _result_path(args):
    path = getattr(args, "result", None)
    if path is None:
        return None
    try:
        check_components(path)
        check_output(path, [], [Path(p) for p in args.forbid_root])
    except Refusal:
        return None
    return path


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        code, result = COMMANDS[args.command](args)
    except Refusal as exc:
        code, result = exc.exit_code, dict(status="REFUSED", reason=exc.code, **exc.detail)
    except GuardCBreach as exc:
        code, result = EXIT_GUARD_C, dict(status="GUARD_C_BREACH", reason=str(exc))
    except BundleError as exc:
        code, result = EXIT_BREACH, dict(status="BUNDLE_REFUSED", reason=str(exc)[:120])
    result = dict(label=LABEL, command=args.command, exit_code=code, **result)
    line = json.dumps(to_plain(result), sort_keys=True)
    print(line)
    path = _result_path(args)
    if path is not None:
        with Path(path).open("x", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
