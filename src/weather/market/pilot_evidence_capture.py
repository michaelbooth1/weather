"""Latched all-band capture, priority books and count-only F0 readiness."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import math
import time

from weather.market.pilot_evidence_contract import BUILTIN_SPECS, F0_COMMIT, strict_json
from weather.market.pilot_evidence_coverage import Coverage, event_bands, event_slug
from weather.market.pilot_evidence_public import CLOB, GAMMA, RetryPending
from weather.market.pilot_evidence_schedule import Scheduler, capacity
from weather.market.pilot_evidence_store import CaptureStopped, stamp
from weather.market.pilot_evidence_stream import MarketStream
from weather.market.pilot_evidence_health import BANK_BYTES, receipt_digest
from weather.market.pilot_evidence_supervisor import validate_output


def readiness_from_capture(args, store):
    """Verify the active recorder's scoped comparison without another REST budget."""
    path = Path(args.capture_health)
    validate_output(path.parent, new=False)
    if (path.name != "health.json" or path.is_symlink() or
            getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
        raise ValueError("redirected/non-health capture receipt refused")
    with path.open("rb") as stream:
        raw = stream.read(BANK_BYTES + 1)
    source = strict_json(raw, max_bytes=BANK_BYTES)
    if source.get("health_receipt_sha256") != receipt_digest(source):
        raise ValueError("capture health checksum mismatch or concurrent write; retry check")
    now = time.monotonic_ns()
    fresh = lambda r, seconds: (isinstance(r, dict) and isinstance(r.get("receipt_monotonic_ns"), int)
                              and 0 <= (now - r["receipt_monotonic_ns"]) / 1e9 <= seconds)
    coverage = source.get("coverage", {})
    specs = {s.id: s for s in BUILTIN_SPECS}
    expected = {event_slug(specs[m], d) for m in args.market for d in args.event_date}
    events, tokens = coverage.get("events", {}), coverage.get("tokens", {})
    ready = (source.get("phase") == "running" and source.get("final") is False and fresh(source, 15) and
             source.get("clock_anchors", {}).get("end_utc") == args.end_utc.isoformat() and
             coverage.get("f0_commit") == F0_COMMIT and coverage.get("ready_for_capture") is True and
             set(events) == expected and bool(tokens) and coverage.get("capacity", {}).get("feasible") is True)
    for slug, event in events.items():
        ready = ready and (event.get("discovered") and event.get("f0_discovery_agrees") and
                          fresh(event.get("metadata_received"), args.metadata_seconds * 1.1) and
                          bool(event.get("tokens")) and set(event["tokens"]).issubset(tokens))
    membership = {t for event in events.values() for t in event.get("tokens", [])}
    ready = ready and membership == set(tokens)
    conditions = {}
    for token, state in tokens.items():
        ready = ready and (state.get("event") in events and token in events[state["event"]]["tokens"] and
                           state.get("baseline_taken_at") is not None and fresh(state.get("last_rest"), args.max_age_seconds))
        conditions.setdefault((state.get("event"), state.get("condition_id")), []).append(token)
    ready = bool(ready and all(cid and len(values) == 2 for (_, cid), values in conditions.items()))
    source_fresh = bool(tokens) and all(state.get("baseline_usable") and
        -args.max_mark_delay_seconds <= state["source_age_at_observation"] +
        (now - state["source_observed_at"]["receipt_monotonic_ns"]) / 1e9 <= args.max_age_seconds
        for state in tokens.values())
    coverage = {**coverage, "ready_for_capture": ready, "accuracy_qualified": False,
                "source_freshness_ready": source_fresh,
                "coverage_ready": ready and source_fresh and not coverage.get("open_intervals"),
                "readiness_basis": "fresh checksummed live capture; no additional public requests"}
    store.coverage = lambda: coverage
    store.write("readiness_result", {"capture_health_sha256": hashlib.sha256(raw).hexdigest(),
                                     "capture_receipt_utc": source.get("receipt_utc"), "coverage": coverage})
    return "readiness_complete" if ready else "readiness_incomplete"


def f0_discovery_pairs(event):
    """Independent pre-reward/ranking extraction of F0's exact Yes/No universe.

    This is the frozen mm_stage2_selection.selection loop's identity contract,
    not an import or invocation of F0's trading/selection implementation.
    """
    result = {}
    for band in event["markets"]:
        tokens, outcomes = band["clobTokenIds"], band["outcomes"]
        tokens = strict_json(tokens) if isinstance(tokens, str) else tokens
        outcomes = strict_json(outcomes) if isinstance(outcomes, str) else outcomes
        cid = band["conditionId"]
        if outcomes != ["Yes", "No"] or len(tokens) != 2 or len(set(tokens)) != 2 or cid in result:
            raise ValueError("F0 pre-filter discovery would refuse")
        result[cid] = tuple(tokens)
    return result


class PublicCapture:
    def __init__(self, args, store, http):
        self.args, self.store, self.http = args, store, http
        specs = {spec.id: spec for spec in BUILTIN_SPECS}
        self.expected = [(specs[m], d) for m in args.market for d in args.event_date]
        self.coverage = Coverage(store, [event_slug(s, d) for s, d in self.expected],
                                 max_age=args.max_age_seconds, max_delay=args.max_mark_delay_seconds)
        self.bands = self.coverage.bands
        self.coverage.metadata_seconds = args.metadata_seconds
        self.scheduler = Scheduler(store, http.gate)
        self.jobs = self.scheduler.jobs
        self.stream = MarketStream(store, http.gate, self.coverage.eligible_stream_tokens,
                                   coverage=self.coverage, max_age=args.max_age_seconds,
                                   max_delay=args.max_mark_delay_seconds)
        self.reward_cursors, self.reward_seen = {}, {}
        self.book_batch = 0
        self.capacity_receipt = None
        self.max_book_body_bytes = 0
        store.coverage = self.snapshot
        self.scheduler.add("books", args.rest_book_seconds, self.books, immediate=True)

    @property
    def baselined(self):
        return {t for t, row in self.coverage.tokens.items() if row["baseline_valid_at"] is not None}

    def tokens(self):
        return sorted(self.coverage.tokens)

    def snapshot(self):
        result = self.coverage.snapshot()
        result["schedule"] = self.scheduler.snapshot()
        result["capacity"] = self.capacity_receipt
        result["f0_commit"] = F0_COMMIT
        result["max_book_response_bytes"] = self.max_book_body_bytes
        return result

    def discover(self, spec, day):
        slug = event_slug(spec, day)
        try:
            event = self.http.once(GAMMA + "/events/slug/" + slug)
            bands = event_bands(event, spec, day)
        except (ValueError, OSError):
            self.coverage.interval("event_discovery_pending", slug, boundary=self.coverage.begin)
            raise
        try:
            added = self.coverage.discover(bands, stamp())
        except ValueError as exc:
            self.store.fail("identity_conflict", event=slug, error=str(exc))
            raise CaptureStopped("identity_conflict") from None
        try:
            expected = f0_discovery_pairs(event)
            actual = {b["condition_id"]: tuple(b["token_ids"]) for b in bands}
            agrees = expected == actual
        except (ValueError, KeyError, TypeError):
            agrees = False
        self.coverage.events[slug]["f0_discovery_agrees"] = agrees
        self.coverage.interval("f0_discovery_mismatch", slug, bad=not agrees, frozen_f0=F0_COMMIT)
        for band in added:
            cid = band["condition_id"]
            self.store.write("band_identity", band)
            self.scheduler.add("reward:" + cid, self.args.terms_seconds, lambda c=cid: self.reward(c))
            self.scheduler.add("fee:" + cid, self.args.fee_seconds,
                               lambda c=cid: self.http.once(CLOB + "/clob-markets/" + c))
            for token in band["token_ids"]:
                self.scheduler.add("fee-rate:" + token, self.args.fee_rate_seconds,
                                   lambda t=token: self.http.once(CLOB + "/fee-rate", params={"token_id": t}))
        if added:
            self.scheduler.spread()
            self.jobs["books"].due = time.monotonic()  # Baselines precede lower-priority work.
            projection = capacity(len(self.bands), len(self.expected), terms=self.args.terms_seconds,
                fees=self.args.fee_seconds, metadata=self.args.metadata_seconds,
                fee_rates=self.args.fee_rate_seconds, rps=self.args.max_rest_rps,
                book_target=self.args.rest_book_seconds, batches=math.ceil(len(self.tokens()) / 100))
            self.capacity_receipt = projection
            self.store.write("capacity_projection", projection)
            # Never sacrifice the independent book fallback to satisfy lower work.
            # If all targets do not fit, record that fact and keep books first.
            self.coverage.interval("capacity_infeasible", "schedule", bad=not projection["feasible"], **projection)
            if len(self.tokens()) > 200:
                self.store.fail("universe_cap", tokens=len(self.tokens()))
                raise CaptureStopped("universe_cap")
        return True

    def books(self, only_new=False):
        tokens = self.tokens()
        if only_new:
            tokens = [t for t in tokens if t not in self.baselined]
        if not tokens:
            return True
        batches = [tokens[i:i + 100] for i in range(0, len(tokens), 100)]
        if self.book_batch >= len(batches):
            self.book_batch = 0
        batch = batches[self.book_batch]
        sent = stamp()
        rows = self.http.once(CLOB + "/books", body=[{"token_id": t} for t in batch])
        received = stamp()
        self.max_book_body_bytes = max(self.max_book_body_bytes, self.http.last_body_bytes)
        if not isinstance(rows, list):
            raise ValueError("book array missing")
        assets = [r.get("asset_id") for r in rows if isinstance(r, dict)]
        if len(assets) != len(rows) or len(set(assets)) != len(assets) or set(assets) - set(batch):
            self.coverage.interval("book_response_scope", "REST", boundary=sent)
            raise ValueError("unexpected/repeated book asset")
        self.coverage.interval("book_response_scope", "REST", bad=False)
        for token in set(batch) - set(assets):
            self.coverage.interval("book_baseline_missing", token, boundary=self.coverage.tokens[token]["last_rest"] or self.coverage.begin)
        for row in rows:
            token = row["asset_id"]
            self.coverage.book(row, token, received, source="rest", request_start=sent)
            self.coverage.interval("book_baseline_missing", token, bad=False)
        self.book_batch += 1
        if self.book_batch < len(batches):
            return False  # Yield at the request boundary even with a >100-token universe.
        self.book_batch = 0
        return True

    def reward(self, cid):
        cursor = self.reward_cursors.get(cid)
        page = self.http.once(CLOB + "/rewards/markets/" + cid,
                              params={"next_cursor": cursor} if cursor else None)
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            raise ValueError("reward page shape")
        next_cursor = page.get("next_cursor")
        if next_cursor in (None, "", "LTE=", "-1"):
            self.reward_cursors.pop(cid, None)
            self.reward_seen.pop(cid, None)
            return True
        seen = self.reward_seen.setdefault(cid, set())
        if not isinstance(next_cursor, str) or next_cursor in seen or len(seen) >= 9:
            self.reward_cursors.pop(cid, None)
            self.reward_seen.pop(cid, None)
            raise ValueError("reward cursor/page bound")
        seen.add(next_cursor)
        self.reward_cursors[cid] = next_cursor
        return False

    def readiness(self):
        for spec, day in self.expected:
            try:
                self.discover(spec, day)
            except (ValueError, OSError):
                pass
            try:
                while self.books() is False:
                    pass
            except (ValueError, OSError):
                pass
        self.coverage.freshness()
        snapshot = self.snapshot()
        self.store.write("readiness_result", {"f0_commit": F0_COMMIT,
            "comparison_scope": "all bands before F0 reward/ranking filters; no F0 module executed",
            "coverage": snapshot, "ready_for_capture": snapshot["ready_for_capture"],
            "accuracy_qualified": False})
        return "readiness_complete" if snapshot["ready_for_capture"] else "readiness_incomplete"

    def run(self):
        for spec, day in self.expected:
            slug = event_slug(spec, day)
            self.coverage.interval("event_discovery_pending", slug, boundary=self.coverage.begin)
            self.scheduler.add("event:" + slug, self.args.metadata_seconds,
                               lambda s=spec, d=day: self.discover(s, d), immediate=True)
        self.scheduler.add("time", self.args.time_sample_seconds,
                           lambda: self.http.once(CLOB + "/time"), immediate=True)
        self.stream.start()
        last_health = 0.0
        try:
            while True:
                self.store.check()
                if not self.stream.is_alive():
                    self.store.fail("stream_thread_ended")
                    raise CaptureStopped("stream_thread_ended")
                self.scheduler.service()
                now = time.monotonic()
                if now - last_health >= 1:
                    self.coverage.freshness()
                    self.store.health()
                    last_health = now
        finally:
            joined = self.stream.shutdown()
            self.store.counts["stream_threads_joined"] = int(joined)
            if not joined:
                self.store.fail("stream_shutdown_timeout")
