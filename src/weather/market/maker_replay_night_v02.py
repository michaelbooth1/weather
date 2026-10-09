"""Create-only bundle v0.2 exports of sealed 88a capture days (maker replay v2 W2, P1/P2).

The v0.2 counterpart of ``maker_replay_night`` (frozen for the exam): the same inventory, ledger,
receipt and module-closure rules, with ``maker_replay_bundle_v02.export`` as the exporter and a
streaming finalize. Nothing re-loads the whole bundle: file hashes are streamed, and book-capture
gaps come from the minutes the exporter recorded. Receipts add bytes and records per kind, the
coverage-group count, the v0.1-equivalent digest, the peak and the runtime. Ledgers are separate
from the v0.1 ledgers, so a date can carry one export of each format.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import time
from types import SimpleNamespace

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import HOST_MAX_RECORDS, HOST_MAX_SECONDS, HOST_MAX_BYTES, regular_path, sha256
from maker_core.replay.calibration import CALIBRATION_DATES
from maker_core.replay.ceilings import process_memory
from maker_core.replay.export_gate import export_permitted
from maker_core.replay.v2.threads import check_thread_pins, thread_record
from maker_core.replay.v2.writer import file_digests
from weather.market.maker_evidence_store import WriterLock
from weather.market.maker_plugin_capture import StopRun, encoded, sealed_segments
from weather.market.maker_plugin_runner import clock_trigger_rows_skipped
from weather.market.maker_replay_bundle import CALIBRATION_KINDS, MAX_INPUT_BYTES, ExportReader
from weather.market.maker_replay_bundle_v02 import export
from weather.market.maker_replay_night import (DEFAULT_INPUT_BYTES, DEFAULT_OUTPUT_BYTES, DEFAULT_SECONDS,
                                               MAX_LEDGER_BYTES, MAX_RECEIPT_BYTES, _inventory, _ledger_days,
                                               _trim_events, _write, module_closure, module_sha256)

KINDS = dict(panel=dict(ledger="panel-v02-ledger.jsonl", kinds=None),
             calibration=dict(ledger="calibration-v02-ledger.jsonl", kinds=CALIBRATION_KINDS))


def book_gaps(conditions, book_minutes):
    """``maker_replay_night._coverage`` over recorded book minutes instead of a loaded bundle."""
    gaps = []
    for c in conditions:
        start = datetime.fromisoformat(c["active_from"])
        day = start.replace(hour=0, minute=0)
        cursor, until = start, datetime.fromisoformat(c["active_until"])
        for minute in book_minutes.get(c["condition_id"], ()):
            at = day + timedelta(minutes=minute)
            if not start <= at < until:
                continue
            if cursor < at:
                gaps.append(dict(condition_id=c["condition_id"], reason="MISSING_BOOK_CAPTURE",
                                 **{"from": cursor.isoformat(), "until": at.isoformat()}))
            cursor = at + timedelta(minutes=1)
        if cursor < until:
            gaps.append(dict(condition_id=c["condition_id"], reason="MISSING_BOOK_CAPTURE",
                             **{"from": cursor.isoformat(), "until": until.isoformat()}))
    return gaps


def _finalize(folder, cap, kind, summary):
    files = file_digests(folder, [p.name for p in folder.iterdir()])
    total = sum(v["bytes"] for v in files.values())
    if total > cap:
        raise StopRun("bundle_output_cap")
    manifest = json.loads((folder / "bundle.json").read_bytes())
    return dict(format="v0.2", files=files, bytes=total, records=sum(s["records"] for s in summary["streams"].values()),
                v01_records=summary["v01_equivalent"]["records"], conditions=len(manifest["conditions"]),
                coverage_groups=summary["coverage_groups"],
                kinds={k: dict(bytes=v["bytes"], records=v["records"], spilled_runs=v["spilled_runs"])
                       for k, v in summary["streams"].items()},
                v01_kinds=summary["v01_kinds"], v01_equivalent=summary["v01_equivalent"],
                gaps=book_gaps(manifest["conditions"], summary["book_minutes"]) if kind == "panel" else [],
                captured_band_cities=sorted({c["market_id"] for c in manifest["conditions"]}))


def export_day(args, kind, *, now=None, clock=time.monotonic, phase=None, environ=None):
    """Export one day. ``environ`` (the CLI passes the process environment) is checked for thread pins.

    In-process callers that pass no ``environ`` are not refused for threads; the receipt still records the
    process environment, the CPU count and the actual pools, with ``pinned`` saying whether the pins held.
    """
    export_permitted(args.day, getattr(args, "owner_decision", None))  # first: before any input
    threads = check_thread_pins(environ) if environ is not None else thread_record(os.environ)
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
        receipt = dict(day=args.day, kind=kind, format="v0.2", status="REFUSED", cities=[], bundle={}, gaps=[],
                       restart_events=[], module_sha256=modules, module_files=len(closure), free_before_bytes=before,
                       active_intervals="MANIFEST_ONLY", threads=threads,
                       restart_completeness="UNKNOWN: only sealed run summaries are retained; crashes may have none")
        failure = reader = None
        try:
            reader = ExportReader(root, args.max_seconds, args.max_input_bytes)
            cities, restarts, gaps, seals = _inventory(reader, args.day)
            receipt.update(cities=cities, restart_events=restarts, gaps=gaps, sealed_segments=seals,
                           discovery_coverage=dict(reader.coverage))
            if not cities:
                raise ValueError("no_discovered_sealed_cities")
            if reader.coverage["segments.unsealed_skipped"]:
                raise ValueError("closed_day_contains_unsealed_segments")
            summary = export(SimpleNamespace(date=args.day, markets=cities, data_root=root, out=pending,
                             max_seconds=args.max_seconds, max_input_bytes=args.max_input_bytes,
                             max_output_bytes=args.max_output_bytes, max_records=HOST_MAX_RECORDS, carry_bundle=[],
                             owner_decision=getattr(args, "owner_decision", None),
                             release_root=release_root, kinds=KINDS[kind]["kinds"]),
                             now=now, reader=reader, phase=phase)
            receipt["bundle"] = _finalize(pending, args.max_output_bytes, kind, summary)
            receipt["bundle"]["support_errors"] = summary["support_errors"]
            receipt["bundle"]["counts"] = summary["counts"]
            receipt["bundle"]["trade_clock_skew"] = summary["trade_clock_skew"]
            # Owner decision SWOB-b (2026-10-07): the clock's trigger-row refusals in the receipt summary,
            # which survives the byte-cap trim that drops reader_coverage. A lower bound, never exact.
            receipt["bundle"]["clock_trigger_rows_skipped"] = clock_trigger_rows_skipped(summary["reader_coverage"])
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
            _trim_events(receipt, MAX_RECEIPT_BYTES - 65536)
            if len(canonical_bytes(receipt)) > MAX_RECEIPT_BYTES - 65536:
                raise StopRun("receipt_byte_cap")
            pending.rename(day_out / "bundle")
            receipt["status"] = "SEALED"
        except (ValueError, KeyError, TypeError, ArithmeticError, OSError, RuntimeError, StopRun,
                MemoryError) as exc:
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
        raw = canonical_bytes(dict(receipt, receipt_sha256=receipt_hash))
        if len(raw) > MAX_RECEIPT_BYTES or (ledger.stat().st_size if ledger.exists() else 0) + len(raw) > MAX_LEDGER_BYTES:
            raise StopRun("ledger_byte_cap")
        with ledger.open("ab") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if failure is not None:
            raise ValueError(receipt["reason"]) from failure
        return receipt


def main(argv=None, *, environ=None):
    """CLI; ``environ`` defaults to the process environment, which must carry the four thread pins."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("module-hash", help="print the v0.2 exporter's repository module-closure hash; reads no data")
    for name, text in (("night", "one all-city v0.2 panel bundle for a closed UTC date"),
                       ("calibration", "v0.2 descriptor/coverage/trade bundle for a calibration date")):
        run = commands.add_parser(name, help=text)
        run.add_argument("--day", required=True)
        run.add_argument("--data-root", type=Path, required=True)
        run.add_argument("--out", type=Path, required=True)
        run.add_argument("--release-root", type=Path)
        run.add_argument("--expected-module-sha256")
        run.add_argument("--max-input-bytes", type=int, default=DEFAULT_INPUT_BYTES)
        run.add_argument("--max-output-bytes", type=int, default=DEFAULT_OUTPUT_BYTES)
        run.add_argument("--max-seconds", type=float, default=DEFAULT_SECONDS)
        run.add_argument("--owner-decision", type=Path, help="signed maker-replay-v2-v1 decision (panel dates only)")
    args = parser.parse_args(argv)
    if args.command == "module-hash":
        closure = module_closure()
        print(json.dumps(dict(module_sha256=module_sha256(closure), files=len(closure)), sort_keys=True))
        return 0
    try:
        receipt = export_day(args, "panel" if args.command == "night" else "calibration",
                             environ=os.environ if environ is None else environ)
    except (ValueError, KeyError, TypeError, ArithmeticError, OSError, RuntimeError, StopRun) as exc:
        parser.exit(2, f"{args.command} refused: {type(exc).__name__}: {exc}\n")
    print(json.dumps({k: receipt[k] for k in ("status", "day", "kind", "format", "cities", "module_sha256")},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
