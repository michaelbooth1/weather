"""Workstation composition for public shadow capture and offline agreement.

The native launcher owns host admission, shared exclusion and child cleanup.
Provider inputs are an explicit immutable public capture, never ambient data.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import time

from maker_core.contracts import Unavailable
from maker_core.evidence.journal import canonical_bytes, digest, plain
from maker_core.replay.bundle import _json, regular_path
from maker_core.shadow.agreement import evaluate
from maker_core.shadow.public_feed import Feed
from maker_core.shadow.runner import Runner
from maker_core.shadow.session import Manifest, Tape
from maker_core.venue.public_read import HttpReads, PublicAdapter, MarketStream
from weather.market.maker_plugin.clock import WeatherInformationClock
from weather.market.maker_plugin.fair_value import WeatherFairValue
from weather.market.maker_plugin.inputs import event_identity
from weather.market.maker_plugin.universe import WeatherUniverse
from weather.paths import data_path


def read_bound(path, expected):
    path = regular_path(path)
    if not path.is_file() or path.stat().st_size > 2*1024**2:
        raise ValueError("shadow_input_size")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("shadow_input_digest")
    return _json(raw)


class WeatherDomain:
    def __init__(self, captures):
        allowed = {"discovery", "books", "band_rows", "bulletins", "forecasts", "snapshots",
                   "explanations", "source_rows", "triggers"}
        if set(captures) - allowed:
            raise ValueError("unlisted_provider_input")
        self.universe = WeatherUniverse(**{k: captures.get(k, ()) for k in ("discovery", "books", "band_rows")})
        self.provider = WeatherFairValue(self.universe, **{k: captures.get(k, ()) for k in (
            "bulletins", "forecasts", "snapshots", "explanations", "source_rows")})
        self.clock = WeatherInformationClock(self.universe, **{k: captures.get(k, ()) for k in ("triggers", "bulletins")})

    def descriptors(self, at):
        return self.universe.discover(at, 2).markets

    def records(self, feed, at):
        rows = []
        for cid, market in sorted(feed.markets.items()):
            spec, target = event_identity(market.event_id)
            descriptor = {"market": plain(market), "horizon_days": (target-at.astimezone(spec.tz).date()).days}
            rows.append(feed.record(cid, "descriptor", at, descriptor, market.source_hashes))
            view = self.provider.evaluate(market, at)
            rows.append(feed.record(cid, "outcome_view", at,
                        {"available": not isinstance(view, Unavailable), "value": plain(view)}, descriptor))
            events = self.clock.upcoming((market,), at-timedelta(minutes=10), at+timedelta(minutes=3))
            events += self.clock.observe((market,), at)
            rows.append(feed.record(cid, "info_event", at, {"events": plain(events)}, descriptor))
        return rows


def assert_launcher():
    """Refuse a bare command: require the parent-owned, write-locked admission."""
    if os.name != "nt":
        raise ValueError("public_shadow_requires_windows_launcher")
    path = regular_path(data_path("logs", "heavy_workload.lock"))
    if path.stat().st_size > 16384:
        raise ValueError("shadow_lease_size")
    lease = _json(path.read_bytes())
    if (lease["execution_host_profile"] != "workstation_public_shadow"
            or lease["pid"] != os.getppid()
            or not lease["workload"].startswith("WorkstationPublicShadow-")):
        raise ValueError("public_shadow_parent_lease")
    try:
        with path.open("r+b"):
            pass
    except PermissionError:
        return
    raise ValueError("public_shadow_lease_not_owned")


def public_session(manifest, captures, output, stop_file, *, clock=lambda: datetime.now(timezone.utc),
                   transport_factory=HttpReads, stream_factory=MarketStream):
    now = clock()
    if not manifest.start <= now < manifest.end or (now-manifest.start).total_seconds() > 2:
        raise ValueError("session_missed_frozen_start")
    domain = WeatherDomain(captures)
    selected = {c.condition_id for c in manifest.conditions}
    markets = tuple(m for m in domain.descriptors(now) if m.condition_id in selected)
    if {m.condition_id for m in markets} != selected:
        raise ValueError("provider_scope_mismatch")
    for market in markets:
        _, target = event_identity(market.event_id)
        if dict(manifest.target_dates)[market.condition_id] != target.isoformat():
            raise ValueError("local_target_date_binding")
    if digest(captures) != manifest.configuration_digest:
        raise ValueError("provider_configuration_binding")
    stop_file = regular_path(stop_file)
    if stop_file.exists():
        raise ValueError("kill_latch_already_present")
    tape = Tape(output, manifest)
    runner, feed = Runner(manifest, tape), Feed(markets)
    stream = None
    reason, final = "interval_end", None
    try:
        # Only allowlisted public projections; never persist an SDK/HTTP object.
        tape.record("provenance", artifact=tape.artifact(captures))
        adapter = PublicAdapter(transport_factory(), clock=clock)
        stream = stream_factory(tuple(feed.assets))
        next_book, next_terms, next_ping = now, now, now
        while clock() < manifest.end:
            if stop_file.exists():
                reason = "owner_kill"
                break
            rows = []
            received = stream.receive()
            if received is not None:
                rows.extend(feed.stream(clock(), received))
            now = clock()
            if now >= next_ping:
                stream.ping()
                next_ping = now + timedelta(seconds=5)
            if now >= next_terms:
                # Timestamp each actual response; never assign late bytes to a minute.
                for cid in sorted(feed.markets):
                    at, body = adapter.read("rewards", cid)
                    rows.append(feed.terms(cid, at, body))
                at = clock()
                rows.extend(domain.records(feed, at))
                next_terms = at + timedelta(seconds=50)
            if now >= next_book:
                for cid, market in sorted(feed.markets.items()):
                    _, yes = adapter.read("book", market.outcome_tokens["YES"])
                    at, no = adapter.read("book", market.outcome_tokens["NO"])
                    rows.append(feed.books(cid, at, yes, no))
                next_book = clock() + timedelta(seconds=2)
            # Group only truly identical local capture instants.
            from itertools import groupby
            deadlines = [e.heap[0] for e in (runner.engine, runner.sensitivity) if e.heap]
            if (runner.at is not None and any(s.legs for s in runner.engine.states.values())
                    and deadlines and clock() > min(deadlines)+timedelta(seconds=.5)):
                # Never pass off a delayed worker as an on-time withdrawal.
                # End continuity at detection; retained scope exposes missing minutes.
                reason = "timer_deadline_missed"
                break
            for at, batch in groupby(sorted(rows, key=lambda r: (r.captured_at, r.sequence)), key=lambda r: r.captured_at):
                runner.advance(at, tuple(batch))
            at = min(clock(), manifest.end)
            if runner.at is None or at > runner.at:
                runner.advance(at)
            if len(runner.engine.latched) == len(feed.markets):
                reason = "continuity_lost"
                break
    except KeyboardInterrupt:
        reason = "owner_interrupt"
    except (ValueError, OSError, KeyError, TypeError) as exc:
        reason = "public_input_failure_" + type(exc).__name__
    finally:
        if stream is not None:
            stream.close()
        if not tape.failed:
            final = runner.stop(min(clock(), manifest.end), reason)
        else:
            tape.abort()
    return {"status": "CLOSED" if final else "INCOMPLETE", "reason": reason,
            "receipt_sha256": final, "economics": "NOT_RUN"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    public = sub.add_parser("public")
    for name in ("manifest", "manifest-sha256", "provider", "provider-sha256", "output", "stop-file"):
        public.add_argument("--"+name, required=True)
    agreement = sub.add_parser("agreement")
    for name in ("source", "receipt-sha256", "output"):
        agreement.add_argument("--"+name, required=True)
    args = parser.parse_args(argv)
    assert_launcher()
    if args.operation == "agreement":
        result = evaluate(Path(args.source), args.receipt_sha256, Path(args.output))
    else:
        manifest = Manifest.restore(read_bound(args.manifest, args.manifest_sha256))
        captures = read_bound(args.provider, args.provider_sha256)
        output = regular_path(args.output)
        for value in (args.manifest, args.provider, args.stop_file):
            path = regular_path(value)
            if path == output or output in path.parents:
                raise ValueError("input_output_overlap")
        while datetime.now(timezone.utc) < manifest.start:
            time.sleep(max(0, min(.25, (manifest.start-datetime.now(timezone.utc)).total_seconds())))
        result = public_session(manifest, captures, output, Path(args.stop_file))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in ("PASS", "CLOSED") else 2


if __name__ == "__main__":
    raise SystemExit(main())
