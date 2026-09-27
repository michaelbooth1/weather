"""Create-only, fixture-tested nightly export of sealed 88a capture days.

No collectors, credentials, scoring or source writes. A day is sealed only by
its terminal SEALED ledger entry; partial directories are retained on refusal.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
from types import SimpleNamespace

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import MAX_BYTES, MAX_RECORDS, load_bundle, regular_path, sha256
from weather.market.maker_evidence_store import WriterLock
from weather.market.maker_plugin.inputs import event_identity, timestamp
from weather.market.maker_plugin_capture import Segment, StopRun, encoded, sealed_segments
from weather.market.maker_replay_bundle import ExportReader, export

MAX_RECEIPT_BYTES = 8 * 1024**2
MAX_LEDGER_BYTES = 64 * 1024**2


def active_intervals(day, exclusions):
    """Minute-aligned half-open UTC intervals; exclusions are prospective inputs."""
    start = datetime.combine(day, datetime.min.time(), timezone.utc)
    spans = []
    for value in exclusions:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d-(?:(?:[01]\d|2[0-3]):[0-5]\d|24:00)", value):
            raise ValueError("invalid_exclude_utc")
        left, right = (sum(int(v) * m for v, m in zip(t.split(":"), (60, 1))) for t in value.split("-"))
        if left >= right:
            raise ValueError("exclude_utc_must_not_wrap_or_be_empty")
        spans.append((left, right))
    spans.sort()
    cursor, result = 0, []
    for left, right in spans:
        if left < cursor:
            raise ValueError("overlapping_exclude_utc")
        if cursor < left:
            result.append((start + timedelta(minutes=cursor), start + timedelta(minutes=left)))
        cursor = right
    if cursor < 1440:
        result.append((start + timedelta(minutes=cursor), start + timedelta(days=1)))
    return result


def interval_rows(intervals):
    return [dict(active_from=a.isoformat(), active_until=b.isoformat()) for a, b in intervals]


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
                if len(gaps) + len(restarts) > MAX_RECORDS:
                    raise StopRun("inventory_event_cap")
    reader.recheck()
    return sorted(cities), restarts, gaps, seals


def _coverage(bundle, intervals):
    """Book gaps within declared activity, without treating maintenance as zero."""
    minutes = {c.condition_id: set() for c in bundle.conditions}
    for row in bundle.records:
        if row.kind == "book":
            minutes[row.condition_id].add(row.captured_at.replace(second=0, microsecond=0))
    gaps = []
    for c in bundle.conditions:
        for left, right in intervals:
            cursor = max(left, c.active_from)
            right = min(right, c.active_until)
            for at in sorted(t for t in minutes[c.condition_id] if cursor <= t < right):
                if cursor < at:
                    gaps.append(dict(condition_id=c.condition_id, reason="MISSING_BOOK_CAPTURE",
                                     **{"from": cursor.isoformat(), "until": at.isoformat()}))
                cursor = at + timedelta(minutes=1)
            if cursor < right:
                gaps.append(dict(condition_id=c.condition_id, reason="MISSING_BOOK_CAPTURE",
                                 **{"from": cursor.isoformat(), "until": right.isoformat()}))
    return gaps


def _finalize_city(folder, intervals, exclusions, cap):
    # Validate the 110l envelope before adding the 110r interval extension.
    # The base reader rejects that extension, so it cannot silently score the
    # maintenance window. 110r owns reader/engine support (not this mission).
    bundle = load_bundle(folder)
    gaps = _coverage(bundle, intervals)
    if exclusions:
        manifest = json.loads((folder / "bundle.json").read_bytes())
        for condition in manifest["conditions"]:
            left, right = timestamp(condition["active_from"]), timestamp(condition["active_until"])
            condition["active_intervals"] = interval_rows(
                [(max(a, left), min(b, right)) for a, b in intervals if max(a, left) < min(b, right)])
        temporary = folder / "bundle.pending.json"
        _write(temporary, manifest)
        # This is still an unsealed pending output, not source or published data.
        os.replace(temporary, folder / "bundle.json")
    files = {}
    for path in sorted(folder.iterdir()):
        raw = path.read_bytes()
        files[path.name] = dict(bytes=len(raw), sha256=sha256(raw))
    if sum(v["bytes"] for v in files.values()) > cap:
        raise StopRun("bundle_output_cap")
    return dict(files=files, bytes=sum(v["bytes"] for v in files.values()), gaps=gaps)


def night(args, *, now=None):
    now = now or datetime.now(timezone.utc)
    day = date.fromisoformat(args.day)
    if day.isoformat() != args.day or day >= now.astimezone(timezone.utc).date():
        raise ValueError("closed_canonical_utc_day_required")
    exclusions = sorted(args.exclude_utc)
    intervals = active_intervals(day, exclusions)
    if not 0 < args.max_output_bytes <= MAX_BYTES or not 0 < args.max_input_bytes <= 1024**3:
        raise ValueError("invalid_byte_limit")
    if not 0 < args.max_seconds <= 300:
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
    ledger = regular_path(out / "panel-ledger.jsonl")
    with WriterLock(out):
        day_out = regular_path(out / args.day)
        if args.day in _ledger_days(ledger) or day_out.exists():
            raise ValueError("day_already_sealed_or_attempted")
        before = shutil.disk_usage(out).free
        day_out.mkdir()
        pending = day_out / "pending"
        pending.mkdir()
        receipt = dict(day=args.day, status="REFUSED", cities=[], bundles={}, gaps=[], restart_events=[],
                       exclusions=exclusions, active_intervals=interval_rows(intervals), free_before_bytes=before,
                       reader_compatibility="REQUIRES_110R_ACTIVE_INTERVALS" if exclusions else "110L",
                       restart_completeness="UNKNOWN: only sealed run summaries are retained; crashes may have none")
        failure = None
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
            # The cap covers discovery and each city's complete 110l input pass.
            # Separate market outputs never truncate an over-cap city/day.
            for city in cities:
                reader.check()
                summary = export(SimpleNamespace(date=args.day, markets=[city], data_root=root, out=pending / city,
                                 max_seconds=args.max_seconds, max_input_bytes=args.max_input_bytes,
                                 max_output_bytes=args.max_output_bytes, max_records=MAX_RECORDS, carry_bundle=[],
                                 release_root=release_root),
                                 now=now, reader=reader)
                receipt["bundles"][city] = _finalize_city(pending / city, intervals, exclusions, args.max_output_bytes)
                receipt["bundles"][city]["exclusions"] = summary["support_errors"]
            final_seals = {folder.name: sha256(encoded(manifest))
                           for _, folder, manifest in sealed_segments(reader, args.day)}
            if final_seals != seals or reader.coverage["segments.unsealed_skipped"]:
                raise ValueError("segment_inventory_changed")
            reader.recheck()
            reader.check()
            receipt["input_bytes"] = reader.bytes_read
            receipt["input_hashes"] = dict(sorted(reader.hashes.items()))
            # Check receipt bound before publishing any final bundle directory.
            if len(canonical_bytes(receipt)) > MAX_RECEIPT_BYTES - 4096:
                raise StopRun("receipt_byte_cap")
            pending.rename(day_out / "bundles")
            receipt["status"] = "SEALED"
        except (ValueError, KeyError, TypeError, ArithmeticError, OSError, RuntimeError, StopRun) as exc:
            failure = exc
            receipt["reason"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            if len(canonical_bytes(receipt)) > MAX_RECEIPT_BYTES - 4096:
                for key in ("bundles", "gaps", "restart_events", "input_hashes", "sealed_segments"):
                    receipt.pop(key, None)
                receipt["details_omitted"] = "receipt_byte_cap; retain pending outputs for inspection"
        receipt["free_after_bytes"] = shutil.disk_usage(out).free
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("night")
    run.add_argument("--day", required=True)
    run.add_argument("--data-root", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--release-root", type=Path, help="explicit immutable releases for calibration-method projection")
    run.add_argument("--exclude-utc", action="append", default=[])
    run.add_argument("--max-input-bytes", type=int, default=1024**3)
    run.add_argument("--max-output-bytes", type=int, default=MAX_BYTES)
    run.add_argument("--max-seconds", type=float, default=300)
    args = parser.parse_args(argv)
    try:
        receipt = night(args)
    except (ValueError, KeyError, TypeError, ArithmeticError, OSError, RuntimeError, StopRun) as exc:
        parser.exit(2, f"night refused: {type(exc).__name__}: {exc}\n")
    print(json.dumps({k: receipt[k] for k in ("status", "day", "cities", "reader_compatibility")}, sort_keys=True))
    return 0
