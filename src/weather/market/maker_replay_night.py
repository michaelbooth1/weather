"""Create-only, fixture-tested exports of sealed 88a capture days.

``night`` writes one all-city panel bundle per closed UTC date; ``calibration``
writes the descriptor/coverage/trade-only bundle the frozen hazard method reads,
for calibration dates only. Bundles carry no active intervals: quote-panel
exclusions belong to the execution manifest (Clarification 2). No collectors,
credentials, scoring or source writes. A day is sealed only by its terminal SEALED
ledger entry; partial directories are retained on refusal.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import HOST_MAX_BYTES, HOST_MAX_RECORDS, HOST_MAX_SECONDS, load_bundle, regular_path, sha256
from maker_core.replay.calibration import CALIBRATION_DATES
from maker_core.replay.ceilings import process_memory
from weather.market.maker_evidence_store import WriterLock
from weather.market.maker_plugin.inputs import event_identity, timestamp
from weather.market.maker_plugin_capture import Segment, StopRun, encoded, sealed_segments
from weather.market.maker_replay_bundle import (CALIBRATION_KINDS, MAX_INPUT_BYTES, OUTPUT_LIMITS, ExportReader,
                                                export)
from weather.paths import SRC_ROOT

MAX_RECEIPT_BYTES = 8 * 1024**2
MAX_LEDGER_BYTES = 64 * 1024**2
DEFAULT_OUTPUT_BYTES = 2 * 1024**3
DEFAULT_INPUT_BYTES = 4 * 1024**3
# The accepted nightly budget (45 minutes), well inside the host's four-hour limit.
DEFAULT_SECONDS = 2700.0
MAX_INVENTORY_EVENTS = 100_000
KINDS = dict(panel=dict(ledger="panel-ledger.jsonl", kinds=None),
             calibration=dict(ledger="calibration-ledger.jsonl", kinds=CALIBRATION_KINDS))


def module_closure():
    """Every repository source module this process has imported, by content hash."""
    root = SRC_ROOT.resolve()
    closure = {}
    for module in list(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if not name or not name.endswith(".py"):
            continue
        path = Path(name).resolve()
        if path.is_relative_to(root):
            closure[path.relative_to(root).as_posix()] = sha256(path.read_bytes())
    return dict(sorted(closure.items()))


def module_sha256(closure):
    return sha256(canonical_bytes(closure))


# Event lists a receipt may shorten to fit its byte bound; each keeps its full count and hash.
TRIMMABLE_EVENTS = (("gaps",), ("restart_events",), ("bundle", "gaps"))


def _trim_events(receipt, limit):
    """Keep a prefix of each event list until the receipt fits; never touch bindings or counts."""
    if len(canonical_bytes(receipt)) <= limit:
        return
    lists = {}
    for path in TRIMMABLE_EVENTS:
        holder = receipt.get(path[0]) if len(path) > 1 else receipt
        if isinstance(holder, dict) and holder.get(path[-1]):
            lists[".".join(path)] = holder, path[-1], list(holder[path[-1]])
    trimmed = {name: dict(total=len(events), sha256=sha256(canonical_bytes(events)))
               for name, (_, _, events) in lists.items()}
    keep = max((len(events) for _, _, events in lists.values()), default=0)
    while keep and len(canonical_bytes(receipt)) > limit:
        keep //= 2
        for name, (holder, key, events) in lists.items():
            holder[key] = events[:keep]
            trimmed[name]["kept"] = len(holder[key])
        receipt["events_trimmed"] = trimmed


def _write(path, value):
    raw = canonical_bytes(value)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise StopRun("receipt_byte_cap")
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return sha256(raw)


def _ledger_days(path):
    if not path.exists():
        return set()
    regular_path(path)
    if path.stat().st_size > MAX_LEDGER_BYTES:
        raise StopRun("ledger_byte_cap")
    days = set()
    with path.open("rb") as handle:
        while line := handle.readline(MAX_RECEIPT_BYTES + 1):
            if len(line) > MAX_RECEIPT_BYTES or not line.endswith(b"\n"):
                raise ValueError("incomplete_or_oversized_panel_ledger")
            row = json.loads(line)
            if row["day"] in days or row["status"] not in ("SEALED", "REFUSED"):
                raise ValueError("invalid_panel_ledger")
            days.add(row["day"])
    return days


def _inventory(reader, day):
    """Only sealed discovery and allowlisted lifecycle journals, never status."""
    cities, restarts, gaps, seals = set(), [], [], {}
    segments = sealed_segments(reader, day)
    for sealed, folder, manifest in segments:
        reader.check()
        segment = Segment(reader, folder, manifest)
        segment_id = folder.name
        seals[segment_id] = sha256(encoded(manifest))
        for name in sorted(manifest["files"]):
            if name not in ("discovery.jsonl", "run_summary.jsonl", "stream_gap.jsonl",
                            "stream_lifecycle.jsonl", "stream_cap.jsonl", "disk_brake.jsonl"):
                continue
            for row in segment.rows(name).values():
                reader.check()
                at = timestamp(row["captured_at_utc"])
                if at.date().isoformat() != day or at > sealed:
                    raise ValueError("invalid_inventory_capture_clock")
                value = json.loads(segment.payload(row))
                identity = dict(segment=segment_id, sequence=row["sequence"],
                                captured_at_utc=at.isoformat(), sealed_segment_sha256=seals[segment_id])
                if name == "discovery.jsonl":
                    if row.get("http_status") != 200:
                        continue
                    for event in value:
                        spec, _ = event_identity(event["slug"])
                        cities.add(spec.id)
                elif name == "run_summary.jsonl":
                    started = timestamp(value["started_at_utc"])
                    if started > at:
                        raise ValueError("future_run_start")
                    restarts.append(dict(identity, reason="RECORDED_88A_RUN", started_at_utc=started.isoformat(),
                                         state=value.get("state"), pid=value.get("pid")))
                elif name != "stream_lifecycle.jsonl" or value.get("state") != "connected":
                    gaps.append(dict(identity, reason=row["kind"].upper(),
                                     details={k: value[k] for k in ("channel", "state", "error_type", "band") if k in value}))
                if len(gaps) + len(restarts) > MAX_INVENTORY_EVENTS:
                    raise StopRun("inventory_event_cap")
    reader.recheck()
    return sorted(cities), restarts, gaps, seals


def _coverage(bundle):
    """Book gaps over each condition's whole active UTC day; maintenance is the manifest's."""
    minutes = {c.condition_id: set() for c in bundle.conditions}
    for row in bundle.records:
        if row.kind == "book":
            minutes[row.condition_id].add(row.captured_at.replace(second=0, microsecond=0))
    gaps = []
    for c in bundle.conditions:
        cursor = c.active_from
        for at in sorted(t for t in minutes[c.condition_id] if c.active_from <= t < c.active_until):
            if cursor < at:
                gaps.append(dict(condition_id=c.condition_id, reason="MISSING_BOOK_CAPTURE",
                                 **{"from": cursor.isoformat(), "until": at.isoformat()}))
            cursor = at + timedelta(minutes=1)
        if cursor < c.active_until:
            gaps.append(dict(condition_id=c.condition_id, reason="MISSING_BOOK_CAPTURE",
                             **{"from": cursor.isoformat(), "until": c.active_until.isoformat()}))
    return gaps


def _finalize(folder, cap, kind):
    bundle = load_bundle(folder, limits=OUTPUT_LIMITS)
    files = {}
    for path in sorted(folder.iterdir()):
        raw = path.read_bytes()
        files[path.name] = dict(bytes=len(raw), sha256=sha256(raw))
    if sum(v["bytes"] for v in files.values()) > cap:
        raise StopRun("bundle_output_cap")
    return dict(files=files, bytes=sum(v["bytes"] for v in files.values()), records=len(bundle.records),
                conditions=len(bundle.conditions), gaps=_coverage(bundle) if kind == "panel" else [],
                captured_band_cities=sorted({c.market_id for c in bundle.conditions}))


def export_day(args, kind, *, now=None, clock=time.monotonic):
    started = clock()
    now = now or datetime.now(timezone.utc)
    day = date.fromisoformat(args.day)
    if day.isoformat() != args.day or day >= now.astimezone(timezone.utc).date():
        raise ValueError("closed_canonical_utc_day_required")
    if kind == "calibration" and day not in CALIBRATION_DATES:
        raise ValueError("calibration_export_restricted_to_calibration_dates")
    closure = module_closure()
    modules = module_sha256(closure)
    expected = getattr(args, "expected_module_sha256", None)
    if expected is not None and expected != modules:
        raise ValueError("exporter_module_hash_mismatch")
    if not 0 < args.max_output_bytes <= HOST_MAX_BYTES or not 0 < args.max_input_bytes <= MAX_INPUT_BYTES:
        raise ValueError("invalid_byte_limit")
    if not 0 < args.max_seconds <= HOST_MAX_SECONDS:
        raise ValueError("invalid_time_limit")
    root, out = regular_path(args.data_root), regular_path(args.out)
    release_root = getattr(args, "release_root", None)
    if release_root is not None:
        release_root = regular_path(release_root)
        if out == release_root or out.is_relative_to(release_root) or release_root.is_relative_to(out):
            raise ValueError("output_release_overlap")
    if root == out or out.is_relative_to(root) or root.is_relative_to(out):
        raise ValueError("output_input_overlap")
    if not root.is_dir() or not out.parent.is_dir():
        raise ValueError("existing_input_and_output_parent_required")
    out.mkdir(exist_ok=True)
    regular_path(out / ".writer.lock")
    ledger = regular_path(out / KINDS[kind]["ledger"])
    with WriterLock(out):
        day_out = regular_path(out / args.day)
        if args.day in _ledger_days(ledger) or day_out.exists():
            raise ValueError("day_already_sealed_or_attempted")
        before = shutil.disk_usage(out).free
        day_out.mkdir()
        pending = day_out / "pending"
        receipt = dict(day=args.day, kind=kind, status="REFUSED", cities=[], bundle={}, gaps=[], restart_events=[],
                       module_sha256=modules, module_files=len(closure), free_before_bytes=before,
                       active_intervals="MANIFEST_ONLY",
                       restart_completeness="UNKNOWN: only sealed run summaries are retained; crashes may have none")
        failure = None
        reader = None
        try:
            reader = ExportReader(root, args.max_seconds, args.max_input_bytes)
            cities, restarts, gaps, seals = _inventory(reader, args.day)
            receipt.update(cities=cities, restart_events=restarts, gaps=gaps, sealed_segments=seals,
                           discovery_coverage=dict(reader.coverage))
            if not cities:
                raise ValueError("no_discovered_sealed_cities")
            if reader.coverage["segments.unsealed_skipped"]:
                # Cannot silently omit a city that exists only in an open segment.
                raise ValueError("closed_day_contains_unsealed_segments")
            # One all-city bundle per UTC date: pack_io.load_days admits one directory per day.
            summary = export(SimpleNamespace(date=args.day, markets=cities, data_root=root, out=pending,
                             max_seconds=args.max_seconds, max_input_bytes=args.max_input_bytes,
                             max_output_bytes=args.max_output_bytes, max_records=HOST_MAX_RECORDS, carry_bundle=[],
                             release_root=release_root, kinds=KINDS[kind]["kinds"]),
                             now=now, reader=reader)
            receipt["bundle"] = _finalize(pending, args.max_output_bytes, kind)
            receipt["bundle"]["support_errors"] = summary["support_errors"]
            receipt["bundle"]["counts"] = summary["counts"]
            receipt["bundle"]["trade_clock_skew"] = summary["trade_clock_skew"]
            final_seals = {folder.name: sha256(encoded(manifest))
                           for _, folder, manifest in sealed_segments(reader, args.day)}
            if final_seals != seals or reader.coverage["segments.unsealed_skipped"]:
                raise ValueError("segment_inventory_changed")
            reader.recheck()
            reader.check()
            final = module_closure()
            if any(final.get(name) != value for name, value in closure.items()):
                raise ValueError("exporter_module_changed_during_export")
            receipt["modules_loaded_during_export"] = sorted(set(final) - set(closure))
            receipt["input_bytes"] = reader.bytes_read
            receipt["input_hashes"] = dict(sorted(reader.hashes.items()))
            # Check receipt bound before publishing the final bundle directory; long event
            # lists are shortened first (full count and hash kept), so they never refuse a day.
            _trim_events(receipt, MAX_RECEIPT_BYTES - 65536)
            if len(canonical_bytes(receipt)) > MAX_RECEIPT_BYTES - 65536:
                raise StopRun("receipt_byte_cap")
            pending.rename(day_out / "bundle")
            receipt["status"] = "SEALED"
        except (ValueError, KeyError, TypeError, ArithmeticError, OSError, RuntimeError, StopRun,
                MemoryError) as exc:
            # A MemoryError unwinds the export's frames first, so the small receipt can still be
            # written: the day is REFUSED and recorded, never left attempted without a receipt.
            failure = exc
            receipt["reason"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        if reader is not None:
            receipt["reader_coverage"] = dict(sorted(reader.coverage.items()))
        receipt.update(runtime_seconds=clock()-started, peak_memory_bytes=process_memory()[1],
                       free_after_bytes=shutil.disk_usage(out).free)
        if len(canonical_bytes(receipt)) > MAX_RECEIPT_BYTES - 4096:
            for key in ("gaps", "restart_events", "input_hashes", "sealed_segments", "reader_coverage"):
                receipt.pop(key, None)
            receipt.get("bundle", {}).pop("gaps", None)
            receipt["details_omitted"] = "receipt_byte_cap; retain outputs for inspection"
        receipt_hash = _write(day_out / "receipt.json", receipt)
        entry = dict(receipt, receipt_sha256=receipt_hash)
        raw = canonical_bytes(entry)
        if len(raw) > MAX_RECEIPT_BYTES or (ledger.stat().st_size if ledger.exists() else 0) + len(raw) > MAX_LEDGER_BYTES:
            raise StopRun("ledger_byte_cap")
        with ledger.open("ab") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if failure is not None:
            raise ValueError(receipt["reason"]) from failure
        return receipt


def night(args, *, now=None):
    return export_day(args, "panel", now=now)


def calibration(args, *, now=None):
    return export_day(args, "calibration", now=now)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("module-hash", help="print the exporter's repository module-closure hash; reads no data")
    inventory = commands.add_parser("universe", help="manifest universe JSON from the sealed panel bundles")
    inventory.add_argument("--bundle", type=Path, action="append", required=True)
    inventory.add_argument("--out", type=Path, required=True, help="new sorted universe JSON file")
    for name, text in (("night", "one all-city panel bundle for a closed UTC date"),
                       ("calibration", "descriptor/coverage/trade bundle for a calibration date")):
        run = commands.add_parser(name, help=text)
        run.add_argument("--day", required=True)
        run.add_argument("--data-root", type=Path, required=True)
        run.add_argument("--out", type=Path, required=True)
        run.add_argument("--release-root", type=Path, help="explicit immutable releases for calibration-method projection")
        run.add_argument("--expected-module-sha256", help="refuse unless the loaded exporter modules hash to this")
        run.add_argument("--max-input-bytes", type=int, default=DEFAULT_INPUT_BYTES)
        run.add_argument("--max-output-bytes", type=int, default=DEFAULT_OUTPUT_BYTES)
        run.add_argument("--max-seconds", type=float, default=DEFAULT_SECONDS)
    args = parser.parse_args(argv)
    if args.command == "universe":
        from maker_core.replay.pack_io import write_json
        from weather.market.maker_replay_universe import universe
        try:
            key = write_json(args.out, universe(args.bundle), 8 * 1024**2)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            parser.exit(2, f"universe refused: {type(exc).__name__}: {exc}\n")
        print(json.dumps(dict(universe_sha256=key), sort_keys=True))
        return 0
    if args.command == "module-hash":
        closure = module_closure()
        print(json.dumps(dict(module_sha256=module_sha256(closure), files=len(closure)), sort_keys=True))
        return 0
    try:
        receipt = (night if args.command == "night" else calibration)(args)
    except (ValueError, KeyError, TypeError, ArithmeticError, OSError, RuntimeError, StopRun) as exc:
        parser.exit(2, f"{args.command} refused: {type(exc).__name__}: {exc}\n")
    print(json.dumps({k: receipt[k] for k in ("status", "day", "kind", "cities", "module_sha256")}, sort_keys=True))
    return 0
