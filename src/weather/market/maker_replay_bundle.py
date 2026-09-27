"""Bounded read-only weather projection into the neutral closed-day replay bundle.

88a inputs must be sealed. Supporting plugin tables use 110h's explicit paths,
open/read/close and changed-file checks; this exporter never calls a collector.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path

from maker_core.evidence.journal import canonical_bytes, plain
from maker_core.contracts import SettlementFact
from maker_core.replay.bundle import FORMAT, MAX_BYTES, MAX_RECORDS, BundleError, Limits, load_bundle, sha256
from maker_core.replay.bundle import regular_path as neutral_path
from maker_core.replay.payloads import market_descriptor
from weather.market.maker_plugin.inputs import body, event_identity, latest, timestamp
from weather.market.maker_plugin_capture import Reader, Segment, StopRun, encoded, sealed_segments
from weather.market.maker_plugin_runner import evaluate_event, captured_book, reward_terms
from weather.market.maker_replay_release import ReleaseSources
from weather.market.maker_plugin.exposure import WeatherExposure
from weather.market.maker_plugin.settlement import WeatherSettlement
from weather.market.maker_plugin.universe import WeatherUniverse
from weather.market.market_registry import BUILTIN_SPECS
from weather.paths import DATA_ROOT


class ExportReader(Reader):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.identities, self.hashes, self.paths = {}, {}, {}

    def read(self, path, *args, **kwargs):
        raw = super().read(path, *args, **kwargs)
        key = str(Path(path).absolute().relative_to(self.root)).replace("\\", "/")
        self.remember(key, path, raw)
        return raw

    def read_release(self, root, path):
        # Explicit second read-only root, sharing the whole night's budgets.
        other = Reader(root, self.max_seconds, self.max_input_bytes, clock=self.clock)
        other.started, other.bytes_read = self.started, self.bytes_read
        raw = other.read(path, 2 * 1024**2)
        self.bytes_read = other.bytes_read
        key = "release:" + Path(path).relative_to(root).as_posix()
        self.remember(key, path, raw)
        return raw

    def remember(self, key, path, raw):
        info = Path(path).stat()
        signature = info.st_size, info.st_mtime_ns, info.st_ino
        if key in self.hashes and self.hashes[key] != sha256(raw):
            raise ValueError("source_changed_between_reads")
        self.identities[key], self.hashes[key] = signature, sha256(raw)
        self.paths[key] = Path(path)

    def recheck(self):
        for key, signature in self.identities.items():
            self.check()
            info = self.paths[key].stat()
            if signature != (info.st_size, info.st_mtime_ns, info.st_ino):
                raise ValueError("source_changed_before_export")


class Projection:
    def __init__(self, day, max_bytes, max_records, check):
        self.day, self.limit, self.max_records, self.check = day, max_bytes, max_records, check
        self.start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        self.end = self.start + timedelta(days=1)
        self.records, self.conditions, self.descriptors, self.tokens = [], {}, {}, {}
        self.size, self.sequence, self.dedup, self.counts = 0, 0, {}, Counter()
        self.connections, self.health = {}, {}

    def add(self, cid, kind, at, payload, hashes, *, changed=False):
        self.check()
        payload = plain(payload)
        key, value_hash = (cid, kind), sha256(canonical_bytes(payload))
        if changed and self.dedup.get(key) == value_hash:
            return
        self.dedup[key] = value_hash
        if not self.start <= at < self.end:
            raise ValueError("projection_outside_capture_day")
        row = dict(sequence=self.sequence, captured_at=at.isoformat(), condition_id=cid, kind=kind,
                   payload=payload, payload_sha256=value_hash, source_hashes=hashes)
        raw = canonical_bytes(row)
        if len(raw) > 1024**2 or self.size + len(raw) > self.limit or len(self.records) >= self.max_records:
            raise StopRun("bundle_output_cap")
        self.records.append(raw)
        self.sequence += 1
        self.size += len(raw)
        self.counts[kind] += 1

    def coverage(self, at, hashes):
        for cid, descriptor in sorted(self.descriptors.items()):
            tokens = tuple(descriptor.outcome_tokens.values())
            healthy_until = min((self.health.get(t, self.start) for t in tokens), default=self.start)
            ok = all(t in self.connections for t in tokens) and healthy_until > at
            self.add(cid, "coverage", at, dict(trade_stream_ok=ok,
                     valid_until_utc=min(healthy_until, at+timedelta(seconds=30)) if ok else at+timedelta(seconds=30)), hashes)

    def stream(self, segment, row, hashes):
        at = timestamp(row["captured_at_utc"])
        value = json.loads(segment.payload(row))
        if row["kind"] in ("stream_gap", "stream_lifecycle"):
            if value.get("channel") != "trades":
                return
            ref = value["subscription"]
            relative = str(segment.folder.relative_to(segment.reader.root / "maker_evidence")).replace("\\", "/")
            if ref["segment"] != relative:
                raise ValueError("subscription_outside_sealed_segment")
            sub = segment.rows(ref["file"])[ref["offset"]]
            raw = segment.payload(sub)
            if sha256(raw) != ref["sha256"] or sub["sequence"] > row["sequence"]:
                raise ValueError("subscription_hash_or_clock")
            subscription = json.loads(raw)
            if subscription["channel"] != "trades":
                raise ValueError("subscription_channel_mismatch")
            group = tuple(sorted(str(t) for t in subscription["tokens"]))
            for token in group:
                if value.get("state") == "connected" and row["kind"] == "stream_lifecycle":
                    self.connections[token] = group
                    self.health[token] = at+timedelta(seconds=30)
                else:
                    self.connections.pop(token, None)
                    self.health.pop(token, None)
        else:
            for trade in value if isinstance(value, list) else [value]:
                if trade.get("event_type") != "last_trade_price":
                    continue
                token = str(trade.get("asset_id"))
                for sibling in self.connections.get(token, ()):
                    self.health[sibling] = at+timedelta(seconds=30)
                if token not in self.tokens:
                    self.counts["unmapped_trades"] += 1
                    continue
                cid, outcome = self.tokens[token]
                if str(trade.get("market", "")).lower() != cid:
                    raise ValueError("trade_condition_mismatch")
                stamp = trade["timestamp"]
                traded = (datetime.fromtimestamp(float(stamp)/1000, timezone.utc)
                          if str(stamp).replace(".", "", 1).isdigit() else timestamp(stamp))
                if traded > at:
                    raise ValueError("future_public_trade_clock")
                self.add(cid, "trade", at, dict(trade_id=str(trade.get("id") or sha256(canonical_bytes(trade))),
                    outcome=outcome, price=trade["price"], size=trade["size"],
                    traded_at_utc=traded, aggressor_side=trade["side"]), hashes)
        self.coverage(at, hashes)


def _support_records(projection, cid, support, hashes):
    for name, time_key in (("snapshots", "captured_at_utc"), ("source_rows", "captured_at_utc"),
            ("forecasts", "captured_at_utc"), ("explanations", "captured_at_utc"),
            ("bulletins", "fetched_at"), ("triggers", "current_captured_at_utc"), ("ledger_rows", "recorded_at_utc")):
        for row in support[name]:
            projection.check()
            at = timestamp(row[time_key])
            if at < projection.end:
                payload = dict(source=name, original_captured_at=at, record=row)
                if name == "source_rows":
                    # Additive projection of captured lineage only. Missing is
                    # explicitly null, never an invented identity calibration.
                    payload["release_calibration_method"] = row.get("release_calibration_method")
                projection.add(cid, "plugin_input", max(at, projection.start), payload, hashes)


def _carry_metadata(args, projection, reader):
    """Carry only prior descriptors/band metadata, so closed bands can settle without fresh books."""
    paths = getattr(args, "carry_bundle", ()) or ()
    if len(paths) > 8:
        raise ValueError("carry_bundle_cap")
    for path in paths:
        reader.check()
        bundle = load_bundle(path, limits=Limits(min(MAX_BYTES, args.max_input_bytes-reader.bytes_read),
                                                 MAX_RECORDS, args.max_seconds))
        reader.bytes_read += bundle.input_bytes
        if bundle.day >= projection.day:
            raise ValueError("carry_requires_earlier_closed_day")
        reader.hashes["carry:" + bundle.day.isoformat()] = bundle.input_hashes["bundle.json"]
        bands = [plain(r.payload["record"]) for r in bundle.records
                 if r.kind == "plugin_input" and r.payload.get("source") == "snapshots"]
        # The same band rows may be retained under multiple conditions.
        bands = list({sha256(canonical_bytes(r)): r for r in bands}.values())
        descriptors = {}
        for row in bundle.records:
            if row.kind == "descriptor":
                descriptors[row.condition_id] = market_descriptor(row.payload["market"])
        for cid, descriptor in sorted(descriptors.items()):
            spec, _ = event_identity(descriptor.event_id)
            if descriptor.domain_id != "weather" or spec.id not in args.markets:
                continue
            hashes = {"carry_bundle": bundle.input_hashes["bundle.json"]}
            projection.conditions[cid] = dict(condition_id=cid, market_id=spec.id, domain_id="weather",
                active_from=projection.start.isoformat(), active_until=projection.start.isoformat())
            if len(projection.conditions) > 2000:
                raise StopRun("condition_cap")
            projection.add(cid, "descriptor", projection.start,
                           dict(market=descriptor, horizon_days=-1), hashes)
            for row in bands:
                if row.get("event_slug") == descriptor.event_id:
                    projection.add(cid, "plugin_input", projection.start,
                        dict(source="snapshots", original_captured_at=row["captured_at_utc"], record=row), hashes)
            ledger = reader.table(reader.root/"settlements"/spec.id/"ledger.jsonl")
            provider = WeatherSettlement(WeatherUniverse(band_rows=bands), ledger_rows=ledger)
            for row in ledger:
                at = timestamp(row["recorded_at_utc"])
                if row.get("event_slug") == descriptor.event_id and projection.start <= at < projection.end:
                    fact = provider.resolve(descriptor, at)
                    if isinstance(fact, SettlementFact):
                        projection.add(cid, "settlement", at, fact, hashes)


def export(args, *, now=None, reader=None):
    day = date.fromisoformat(args.date)
    now = now or datetime.now(timezone.utc)
    if day >= now.date():
        raise ValueError("closed_utc_day_required")
    if not 0 < args.max_seconds <= 300 or not 0 < args.max_input_bytes <= 1024**3:
        raise ValueError("invalid_input_limit")
    if not 0 < args.max_output_bytes <= MAX_BYTES or not 0 < args.max_records <= MAX_RECORDS:
        raise ValueError("invalid_output_limit")
    root, output = neutral_path(args.data_root), neutral_path(args.out)
    if output == root or output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError("output_input_overlap")
    if output.exists() or not output.parent.is_dir():
        raise ValueError("new_output_directory_required")
    for path in getattr(args, "carry_bundle", ()) or ():
        source = neutral_path(path)
        if output == source or output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError("output_carry_overlap")
    reader = reader or ExportReader(root, args.max_seconds, args.max_input_bytes)
    release_root = getattr(args, "release_root", None)
    if release_root is not None:
        release_root = neutral_path(release_root)
        if output == release_root or output.is_relative_to(release_root) or release_root.is_relative_to(output):
            raise ValueError("output_release_overlap")
    sources = ReleaseSources(reader, release_root)
    projection = Projection(day, args.max_output_bytes, args.max_records, reader.check)
    _carry_metadata(args, projection, reader)
    support_written, segments = set(), sealed_segments(reader, args.date)
    last_capture = None
    for sealed, folder, manifest in segments:
        reader.check()
        segment = Segment(reader, folder, manifest)
        captures = segment.captures()
        stream_rows = []
        for name in sorted(manifest["files"]):
            if name in ("trades.jsonl", "stream_lifecycle.jsonl", "stream_gap.jsonl"):
                stream_rows.extend(segment.rows(name).values())
        timeline = sorted([*captures, *stream_rows], key=lambda r: (timestamp(r["captured_at_utc"]), r["sequence"]))
        hashes = {"sealed_segment": sha256(encoded(manifest))}
        for row in timeline:
            at = timestamp(row["captured_at_utc"])
            if at.date() != day or at > sealed or (last_capture is not None and at < last_capture):
                raise ValueError("overlapping_or_invalid_segment_clocks")
            last_capture = at
            if row["kind"] in ("trades", "stream_lifecycle", "stream_gap"):
                projection.stream(segment, row, hashes)
                continue
            if row["kind"] == "rewards":
                for cid in sorted(projection.descriptors):
                    terms = reward_terms(captures, cid, at)
                    if terms is not None:
                        projection.add(cid, "terms", at, terms, hashes, changed=True)
                continue
            if row["kind"] != "books":
                continue
            events = {}
            for capture in captures:
                if capture["kind"] == "discovery" and timestamp(capture["captured_at_utc"]) <= at:
                    for event in body(capture):
                        events.setdefault(event["slug"], []).append(dict(captured_at_utc=capture["captured_at_utc"], event=event))
            for slug, candidates in sorted(events.items()):
                spec, target = event_identity(slug)
                horizon = (target - at.astimezone(spec.tz).date()).days
                if spec.id not in args.markets or not 0 <= horizon <= 2:
                    continue
                result = evaluate_event(captures, latest(candidates, at), at, sources, reader, None)
                support = sources.for_event(slug)
                for entry in result["outcomes"]:
                    cid = entry["condition_id"]
                    # Retain missing descriptors as exclusions, not invented bands.
                    if "descriptor" not in entry:
                        projection.counts["missing_descriptor"] += 1
                        continue
                    descriptor = market_descriptor(entry["descriptor"])
                    projection.descriptors[cid] = descriptor
                    projection.conditions[cid] = dict(condition_id=cid, market_id=spec.id, domain_id=descriptor.domain_id,
                        active_from=projection.start.isoformat(), active_until=projection.end.isoformat())
                    if len(projection.conditions) > 2000:
                        raise StopRun("condition_cap")
                    for outcome, token in descriptor.outcome_tokens.items():
                        if token in projection.tokens and projection.tokens[token] != (cid, outcome):
                            raise ValueError("token_identity_changed")
                        projection.tokens[token] = cid, outcome
                    projection.add(cid, "descriptor", at, dict(market=entry["descriptor"], horizon_days=horizon,
                                   exposure_factors=WeatherExposure().factors(descriptor)), hashes, changed=True)
                    projection.add(cid, "book", at, captured_book(captures, descriptor, at), hashes)
                    terms = reward_terms(captures, cid, at)
                    if terms is not None:
                        projection.add(cid, "terms", at, terms, hashes, changed=True)
                    if "fair_value" in entry:
                        projection.add(cid, "outcome_view", at, dict(available=entry["joins"]["fair_value"], value=entry["fair_value"]), hashes, changed=True)
                    if "clock_events" in entry:
                        projection.add(cid, "info_event", at, dict(events=entry["clock_events"]), hashes, changed=True)
                    else:
                        # Invalidate an earlier empty clock; unknown veto evidence
                        # must never become an implicit permission to keep quoting.
                        projection.add(cid, "info_event", at, dict(events=None), hashes, changed=True)
                    if entry["joins"].get("settlement_fact"):
                        projection.add(cid, "settlement", at, entry["settlement"], hashes, changed=True)
                    if cid not in support_written:
                        _support_records(projection, cid, support, hashes)
                        provider = WeatherSettlement(WeatherUniverse(band_rows=support["snapshots"]),
                                                     ledger_rows=support["ledger_rows"])
                        for ledger in support["ledger_rows"]:
                            recorded = timestamp(ledger["recorded_at_utc"])
                            if projection.start <= recorded < projection.end:
                                fact = provider.resolve(descriptor, recorded)
                                if isinstance(fact, SettlementFact):
                                    projection.add(cid, "settlement", max(at, recorded), fact, hashes)
                        support_written.add(cid)
            projection.coverage(at, hashes)
    if not projection.conditions:
        raise ValueError("no_projectable_sealed_conditions")
    reader.recheck()
    raw = b"".join(projection.records)
    manifest = dict(format=FORMAT, day=args.date, sealed_at=projection.end.isoformat(), provenance="captured",
        conditions=[projection.conditions[k] for k in sorted(projection.conditions)],
        streams=[dict(path="events.jsonl", sha256=sha256(raw), bytes=len(raw), records=len(projection.records))])
    summary = dict(status="EXPORTED_FOR_DIAGNOSTICS", day=args.date, counts=dict(sorted(projection.counts.items())),
        input_bytes=reader.bytes_read, input_hashes=dict(sorted(reader.hashes.items())),
        reader_coverage=dict(sorted(reader.coverage.items())), support_errors=dict(sorted(sources.errors.items())),
        assumptions=["Only sealed 88a segments; plugin tables are captured inputs using 110h unchanged-file checks.",
            "Full UTC active days expose before-discovery/after-last-book gaps; unseen conditions cannot be counted.",
            "Trade health expires 30s after connected/inbound evidence; unrecorded PONGs cannot renew it.",
            "Public trades without IDs use a content hash; identical simultaneous messages deduplicate conservatively.",
            "Derived plugin views/clocks are sampled at book captures; original support clocks are retained.",
            "Closed-band settlements can use --carry-bundle descriptors; empty active intervals grant no quote minutes."])
    manifest_bytes, summary_bytes = canonical_bytes(manifest), canonical_bytes(summary)
    if len(raw)+len(manifest_bytes)+len(summary_bytes) > args.max_output_bytes:
        raise StopRun("bundle_output_cap")
    reader.check()
    output.mkdir()
    for name, content in (("events.jsonl", raw), ("bundle.json", manifest_bytes), ("export.json", summary_bytes)):
        with (output/name).open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    # Output-only validation, still within the global deadline; never mutate source.
    reader.check()
    load_bundle(output)
    reader.check()
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("bundle")
    run.add_argument("--date", required=True)
    run.add_argument("--data-root", type=Path, default=DATA_ROOT)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--markets", nargs="+", choices=[s.id for s in BUILTIN_SPECS], required=True)
    run.add_argument("--release-root", type=Path, help="explicit immutable releases for hash-bound calibration projection")
    run.add_argument("--carry-bundle", action="append", type=Path, default=[],
                     help="prior closed-day neutral bundle: descriptor/band metadata for later settlement only")
    run.add_argument("--max-seconds", type=float, default=300)
    run.add_argument("--max-input-bytes", type=int, default=1024**3)
    run.add_argument("--max-output-bytes", type=int, default=MAX_BYTES)
    run.add_argument("--max-records", type=int, default=MAX_RECORDS)
    args = parser.parse_args(argv)
    try:
        result = export(args)
    except (ValueError, KeyError, TypeError, ArithmeticError, OSError, RuntimeError, StopRun, BundleError) as exc:
        parser.exit(2, f"bundle refused: {type(exc).__name__}: {exc}\n")
    print(json.dumps({k: result[k] for k in ("status", "day", "counts", "input_bytes")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
