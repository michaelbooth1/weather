"""Bundle v0.2 export of a sealed 88a capture day (maker replay v2 W2).

The v0.1 exporter (``maker_replay_bundle``, frozen for the exam) holds every output record in memory,
joins them into a second copy and re-parses the whole bundle to validate it. This path keeps the
same projection, row for row, and changes only where the rows go:

- Rows stream into ``maker_core.replay.v2.writer.BundleWriter``: one sorted stream per kind, with
  bounded external sorting for kinds whose clocks run backwards, and coverage spooled to disk.
- **Coverage groups are trade-stream subscriptions, not sockets.** A token's subscriptions are
  recorded as the frozen projection connects them; conditions whose tokens share exactly the same
  subscriptions form one group. A condition never subscribed shares the always-unhealthy group of
  its kind. The same-coverage refusal still fires if a group's members ever disagree.
- No duplicate elision beyond the projection's own: v0.1 already skips repeated descriptors, terms,
  outcome views, info events and settlements, so a v0.2 day expands to exactly the v0.1 rows.
- Validation streams the written bundle back (two-pass reader and expansion) and requires the
  expanded rows to equal the pushed v0.1 rows by count, bytes and an order-independent hash.

Output is built in a partial sibling folder and renamed only after validation. A refusal removes
the partial folder, so no bundle is left behind.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import shutil

from maker_core.evidence.journal import canonical_bytes, plain
from maker_core.contracts import SettlementFact
from maker_core.replay.bundle import HOST_MAX_BYTES, HOST_MAX_SECONDS, BundleError, sha256
from maker_core.replay.bundle import regular_path as neutral_path
from maker_core.replay.export_gate import export_permitted
from maker_core.replay.payloads import market_descriptor
from maker_core.replay.v2.writer import BundleWriter, validate
from weather.market.maker_plugin.inputs import body, event_identity, latest, timestamp
from weather.market.maker_plugin_capture import Segment, StopRun, encoded, sealed_segments
from weather.market.maker_plugin_runner import CaptureIndex, evaluate_event, captured_book, reward_terms
from weather.market.maker_plugin.settlement import WeatherSettlement
from weather.market.maker_plugin.universe import WeatherUniverse
from weather.market.maker_replay_bundle import (MAX_INPUT_BYTES, OUTPUT_LIMITS, ExportReader, Projection,
                                                _carry_metadata, _raw_support, _support_records)
from weather.market.maker_replay_release import ReleaseSources
from weather.market.maker_plugin.exposure import WeatherExposure
from weather.market.market_registry import BUILTIN_SPECS

ASSUMPTIONS = [
    "Rows are the v0.1 projection's, unchanged; only storage differs (bundle format v0.2).",
    "Coverage groups are trade-stream subscriptions: conditions whose tokens share exactly the same "
    "subscriptions; a group's members must agree at every capture or the day is refused.",
    "No duplicate elision is added; the v0.1 projection already skips repeated payloads.",
]


class _Subscriptions(dict):
    """The frozen projection's ``connections`` map, also remembering every subscription each token joined."""

    def __init__(self):
        super().__init__()
        self.joined = {}

    def __setitem__(self, token, group):
        self.joined.setdefault(token, set()).add(tuple(group))
        super().__setitem__(token, group)


class StreamingProjection(Projection):
    """``Projection`` with rows pushed to a ``BundleWriter`` instead of an in-memory list."""

    def __init__(self, day, max_bytes, max_records, check, kinds, writer, phase=None):
        super().__init__(day, max_bytes, max_records, check, kinds)
        self.connections = _Subscriptions()
        self.writer, self.phase = writer, phase or (lambda label: None)
        self.book_minutes = {}

    def add(self, cid, kind, at, payload, hashes, *, changed=False):
        # Same admission, dedup and row as ``Projection.add``; the row is written, not retained.
        self.check()
        if self.kinds is not None and kind not in self.kinds:
            return
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
        if len(raw) > 1024**2 or self.size + len(raw) > self.limit or self.sequence >= self.max_records:
            raise StopRun("bundle_output_cap")
        self.writer.add(row, raw)
        if kind == "book":
            self.book_minutes.setdefault(cid, set()).add((at - self.start).seconds // 60)
        self.sequence += 1
        self.size += len(raw)
        self.counts[kind] += 1

    def groups(self):
        """Condition -> group ID, keyed by each outcome token's exact set of joined subscriptions."""
        out = {}
        for cid, descriptor in sorted(self.descriptors.items()):
            key = [[outcome, sorted(sorted(g) for g in self.connections.joined.get(token, ()))]
                   for outcome, token in sorted(descriptor.outcome_tokens.items())]
            out[cid] = "sub-" + sha256(canonical_bytes(key))[:24]
        return out


def _project(args, reader, sources, projection):
    """The v0.1 ``export`` loop, unchanged except for its projection sink."""
    day = projection.day
    support_written, segments = set(), sealed_segments(reader, args.date)
    raw_support, last_capture = {}, None
    for sealed, folder, manifest in segments:
        reader.check()
        segment = Segment(reader, folder, manifest)
        captures = segment.captures()
        index = CaptureIndex(captures)
        stream_rows = []
        for name in sorted(manifest["files"]):
            if name in ("trades.jsonl", "stream_lifecycle.jsonl", "stream_gap.jsonl"):
                stream_rows.extend(segment.rows(name).values())
        timeline = sorted([*captures, *stream_rows], key=lambda r: (timestamp(r["captured_at_utc"]), r["sequence"]))
        hashes = {"sealed_segment": sha256(encoded(manifest))}
        projection.phase("segment_loaded")
        for row in timeline:
            at = timestamp(row["captured_at_utc"])
            if at.date() != day or at > sealed or (last_capture is not None and at < last_capture):
                raise ValueError("overlapping_or_invalid_segment_clocks")
            last_capture = at
            if row["kind"] in ("trades", "stream_lifecycle", "stream_gap"):
                projection.stream(segment, row, hashes)
                continue
            if row["kind"] == "rewards":
                named = index.reward_cids(at) if projection.keeps("terms") else set()
                for cid in sorted(projection.descriptors):
                    if named is not None and cid not in named:
                        continue
                    terms = reward_terms(index, cid, at)
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
                if slug not in raw_support:
                    raw_support[slug] = _raw_support(sources.for_event(slug))
                result = evaluate_event(index, latest(candidates, at), at, sources, reader, None)
                support = raw_support[slug]
                for entry in result["outcomes"]:
                    cid = entry["condition_id"]
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
                    projection.add(cid, "book", at, captured_book(index, descriptor, at), hashes)
                    terms = reward_terms(index, cid, at) if projection.keeps("terms") else None
                    if terms is not None:
                        projection.add(cid, "terms", at, terms, hashes, changed=True)
                    if "fair_value" in entry:
                        projection.add(cid, "outcome_view", at, dict(available=entry["joins"]["fair_value"], value=entry["fair_value"]), hashes, changed=True)
                    if "clock_events" in entry:
                        projection.add(cid, "info_event", at, dict(events=entry["clock_events"]), hashes, changed=True)
                    else:
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
        projection.phase("segment_projected")
        segment = captures = index = stream_rows = timeline = None
    raw_support.clear()


def _overlap(output, other):
    return output == other or output.is_relative_to(other) or other.is_relative_to(output)


def export(args, *, now=None, reader=None, phase=None):
    """Export one closed UTC day as bundle v0.2 into the new directory ``args.out``."""
    export_permitted(args.date, getattr(args, "owner_decision", None), now=now)  # first: before any input
    day = date.fromisoformat(args.date)
    now = now or datetime.now(timezone.utc)
    phase = phase or (lambda label: None)
    if day >= now.date():
        raise ValueError("closed_utc_day_required")
    if not 0 < args.max_seconds <= HOST_MAX_SECONDS or not 0 < args.max_input_bytes <= MAX_INPUT_BYTES:
        raise ValueError("invalid_input_limit")
    if not 0 < args.max_output_bytes <= HOST_MAX_BYTES or not 0 < args.max_records:
        raise ValueError("invalid_output_limit")
    root, output = neutral_path(args.data_root), neutral_path(args.out)
    if _overlap(output, root):
        raise ValueError("output_input_overlap")
    if output.exists() or not output.parent.is_dir():
        raise ValueError("new_output_directory_required")
    for path in getattr(args, "carry_bundle", ()) or ():
        if _overlap(output, neutral_path(path)):
            raise ValueError("output_carry_overlap")
    release_root = getattr(args, "release_root", None)
    if release_root is not None:
        release_root = neutral_path(release_root)
        if _overlap(output, release_root):
            raise ValueError("output_release_overlap")
    partial = output.with_name(output.name + ".partial")
    if partial.exists():
        raise ValueError("partial_output_exists")
    reader = reader or ExportReader(root, args.max_seconds, args.max_input_bytes)
    sources = ReleaseSources(reader, args.date, args.markets, release_root)
    partial.mkdir()
    writer = None
    try:
        writer = BundleWriter(partial, max_stream_bytes=args.max_output_bytes)
        projection = StreamingProjection(day, args.max_output_bytes, args.max_records, reader.check,
                                         getattr(args, "kinds", None), writer, phase)
        _carry_metadata(args, projection, reader)
        phase("projecting")
        _project(args, reader, sources, projection)
        if not projection.conditions:
            raise ValueError("no_projectable_sealed_conditions")
        reader.recheck()
        phase("writing")
        manifest = dict(day=args.date, sealed_at=projection.end.isoformat(), provenance="captured",
                        conditions=[projection.conditions[k] for k in sorted(projection.conditions)])
        written = writer.finish(manifest, projection.groups(), check=reader.check)
        if written["manifest_bytes"] + sum(s["bytes"] for s in written["streams"].values()) > args.max_output_bytes:
            raise StopRun("bundle_output_cap")
        phase("validating")
        reader.check()
        checked = validate(partial, written["v01"], limits=OUTPUT_LIMITS, check=reader.check)
        if checked["kinds"] != {k: v["records"] for k, v in written["v01_kinds"].items()}:
            raise BundleError("v02_expansion_kind_counts_differ")
        summary = dict(status="EXPORTED_FOR_DIAGNOSTICS", format="v0.2", day=args.date,
            counts=dict(sorted(projection.counts.items())), input_bytes=reader.bytes_read,
            input_hashes=dict(sorted(reader.hashes.items())), reader_coverage=dict(sorted(reader.coverage.items())),
            support_errors=dict(sorted(sources.errors.items())), trade_clock_skew=projection.skew_summary(),
            streams=written["streams"], coverage_groups=written["coverage_groups"], v01_equivalent=written["v01"],
            v01_kinds=written["v01_kinds"], manifest_bytes=written["manifest_bytes"],
            bundle_bytes=written["manifest_bytes"] + sum(s["bytes"] for s in written["streams"].values()),
            book_minutes={cid: sorted(m) for cid, m in sorted(projection.book_minutes.items())},
            assumptions=ASSUMPTIONS)
        raw = canonical_bytes({k: v for k, v in summary.items() if k != "book_minutes"})
        with (partial / "export.json").open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        reader.check()
        partial.rename(output)
        phase("done")
        return summary
    except BaseException:
        if writer is not None:
            writer.abort()
        shutil.rmtree(partial, ignore_errors=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("bundle")
    run.add_argument("--date", required=True)
    run.add_argument("--data-root", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--markets", nargs="+", choices=[s.id for s in BUILTIN_SPECS], required=True)
    run.add_argument("--release-root", type=Path)
    run.add_argument("--carry-bundle", action="append", type=Path, default=[])
    run.add_argument("--max-seconds", type=float, default=2700)
    run.add_argument("--max-input-bytes", type=int, default=4 * 1024**3)
    run.add_argument("--max-output-bytes", type=int, default=2 * 1024**3)
    run.add_argument("--max-records", type=int, default=2**31)
    run.add_argument("--owner-decision", type=Path, help="signed maker-replay-v2-v1 decision (panel dates only)")
    args = parser.parse_args(argv)
    try:
        result = export(args)
    except (ValueError, KeyError, TypeError, ArithmeticError, OSError, RuntimeError, StopRun, BundleError) as exc:
        parser.exit(2, f"bundle refused: {type(exc).__name__}: {exc}\n")
    print(json.dumps({k: result[k] for k in ("status", "format", "day", "counts", "bundle_bytes")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
