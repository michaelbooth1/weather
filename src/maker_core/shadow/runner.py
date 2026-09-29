"""Incremental captured-time orchestration of the shared replay lifecycle.

Only local hypothetical state is applied. A trade-health gap permanently ends
continuity; reconnection cannot restore inventory that was never observed.
"""
from dataclasses import replace
from datetime import timedelta
import heapq

from maker_core.evidence.journal import canonical_bytes, digest
from maker_core.replay.bundle import Bundle, CapturedRecord, _freeze
from maker_core.replay.lifecycle import Lifecycle, EPSILON
from maker_core.replay.payloads import decode
from maker_core.shadow.codec import checked


class ShadowEngine(Lifecycle):
    def __init__(self, manifest, *, emit, artifact, config=None):
        bundle = Bundle(manifest.start.date(), manifest.end, "shadow", manifest.conditions, (), {}, 0)
        super().__init__((bundle,), config or manifest.config)
        self.emit, self.artifact = emit, artifact
        self.manifest = manifest
        self.heap, self.pending = [], set()
        self.horizon, self.end = manifest.end, manifest.end
        self.latched, self.gaps, self.input_artifact = {}, [], None
        self.latest_refs = {}
        for c in manifest.conditions:
            self.schedule(c.active_from)
            self.schedule(c.active_until)

    def snapshot(self):
        return {"cash": self.cash, "states": self.states, "ended": self.ended,
                "latched": self.latched, "gaps": self.gaps,
                "trades_seen": tuple(sorted((cid, trade, value) for (cid, trade), value in self.trades_seen.items()))}

    def decide_inputs(self, value):
        self.input_artifact = self.artifact(value)
        return super().decide_inputs(value)

    def record_decision(self, cid, at, decision):
        before = self.artifact(self.snapshot())
        super().record_decision(cid, at, decision)
        after = self.artifact(self.snapshot())
        self.latest_refs[cid] = self.emit("decision", at=at, condition_id=cid,
            decision=decision, typed_input=self.input_artifact,
            state_before=before, state_after=after)
        self.input_artifact = None

    def ingest(self, row, at):
        state = self.states[row.condition_id]
        # Decode before application; a corrupt row cannot leave an old value usable.
        try:
            value = decode(row)
        except (ValueError, KeyError, TypeError, ArithmeticError):
            state.latest.pop(row.kind, None)
            self.latch(row.condition_id, at, "INVALID_" + row.kind.upper())
            return
        if row.kind == "terms" and "terms" in state.latest:
            old = state.latest["terms"]
            if (old.min_size, old.max_spread_cents, old.rate_per_day) != (
                    value.min_size, value.max_spread_cents, value.rate_per_day):
                self.pull(row.condition_id, at, "TERMS_CHANGED")
        if row.kind == "descriptor":
            if value.market.plugin_version != self.manifest.plugin_identity:
                self.latch(row.condition_id, at, "PLUGIN_IDENTITY_CHANGED")
            if "descriptor" in state.latest and value.market != state.latest["descriptor"].market:
                self.latch(row.condition_id, at, "MARKET_RULES_CHANGED")
        if row.kind == "outcome_view" and hasattr(value, "model_id") and value.model_id != self.manifest.model_identity:
            self.latch(row.condition_id, at, "MODEL_IDENTITY_CHANGED")
        super().ingest(row, at)
        if row.kind == "terms":
            self.schedule(value.as_of_utc + timedelta(seconds=60))
        if row.kind == "coverage" and not value.trade_stream_ok:
            self.latch(row.condition_id, at, "TRADE_CAPTURE_GAP")

    def latch(self, cid, at, reason):
        if cid not in self.latched:
            self.latched[cid] = reason
            self.gaps.append({"condition_id": cid, "start": at, "end": None, "reason": reason})
            self.emit("gap", condition_id=cid, at=at, reason=reason, end=None)
            self.pull(cid, at, reason)

    def valid_coverage(self, state, at):
        covered, reason = super().valid_coverage(state, at)
        if covered and (at - state.latest["terms"].as_of_utc).total_seconds() >= 60:
            return False, "TERMS_CAPTURE_GAP"
        return covered, reason

    def tick(self, cid, at):
        state = self.states[cid]
        health = state.latest.get("coverage")
        if health and at >= health.valid_until_utc and self.active(cid, at):
            self.latch(cid, at, "TRADE_CAPTURE_GAP")
        if cid in self.latched:
            self.pull(cid, at, self.latched[cid])
            state.covered = False
            return
        super().tick(cid, at)

    def step(self, at, rows):
        # Same-time trades consume the preceding legs, in venue-time/sequence order.
        trades = sorted((r for r in rows if r.kind == "trade"),
                        key=lambda r: (decode(r).traded_at, r.sequence))
        for row in trades:
            if row.condition_id not in self.latched:
                self.on_trade(row, at)
        for row in sorted((r for r in rows if r.kind != "trade"), key=lambda r: r.sequence):
            self.ingest(row, at)
        for cid in sorted(self.states):
            self.tick(cid, at)
        self.emit("applied", at=at, state=self.artifact(self.snapshot()))
        # Evidence is on disk. Keep only portfolio lots and bounded dedup in memory.
        self.decisions.clear()
        self.books.clear()
        self.fills.clear()


class Runner:
    def __init__(self, manifest, tape):
        self.manifest, self.tape = manifest, tape
        self.at, self.sequence, self.events = None, -1, 0
        self.stopped, self.last_minute = False, None
        self.processing_at = manifest.start
        self.engine = ShadowEngine(manifest, emit=self.emit, artifact=tape.artifact)
        # Sensitivity state is completely independent; no economics are evaluated.
        self.sensitivity = ShadowEngine(manifest, emit=self.emit_sensitivity, artifact=tape.artifact,
                                        config=replace(manifest.config, fill_bound="at_price"))
        minute = manifest.start.replace(second=0, microsecond=0)
        self.next_minute = minute if minute == manifest.start else minute + timedelta(minutes=1)

    def emit(self, event, **payload):
        return self.tape.record(event, processed_at=self.processing_at, **payload)

    def emit_sensitivity(self, event, **payload):
        return self.tape.record("sensitivity_" + event, processed_at=self.processing_at, **payload)

    def state(self):
        return {"primary": self.engine.snapshot(), "sensitivity": self.sensitivity.snapshot(),
                "last_minute": self.last_minute, "stopped": self.stopped}

    def _step(self, at, rows=()):
        self.events += 1
        if self.events > self.manifest.max_events:
            raise ValueError("shadow_event_ceiling")
        self.tape.now = at
        for engine in (self.engine, self.sensitivity):
            while engine.heap and engine.heap[0] <= at:
                engine.pending.remove(heapq.heappop(engine.heap))
            engine.step(at, rows)
        self.at = at
        if at == self.next_minute and at < self.manifest.end:
            self.last_minute = at
            self.emit("minute", slot=at, expected=sorted(self.engine.states),
                      latest=self.engine.latest_refs, state=self.tape.artifact(self.state()),
                      coverage={cid: {"covered": s.covered, "reason": s.reason,
                                      "active": self.engine.active(cid, at), "legs": s.legs}
                                for cid, s in sorted(self.engine.states.items())})
            self.next_minute += timedelta(minutes=1)
        self.tape.rotate(at, self.tape.artifact(self.state()))

    def advance(self, at, rows=()):
        try:
            self._advance(at, rows)
        except BaseException:
            self.stopped = True
            for engine in (self.engine, self.sensitivity):
                for state in engine.states.values():
                    state.legs = ()
            if not self.tape.closed:
                self.tape.abort()
            raise

    def _advance(self, at, rows=()):
        """A batch has ONE actual capture instant, never a rounded minute slot."""
        if self.stopped or not self.manifest.start <= at <= self.manifest.end or (self.at and at <= self.at):
            raise ValueError("shadow_clock_or_state")
        self.processing_at = at
        rows = tuple(rows)
        if len(rows) > 1024:
            raise ValueError("batch_cap")
        validated = []
        for row in sorted(rows, key=lambda r: r.sequence):
            if (not isinstance(row, CapturedRecord) or row.condition_id not in self.engine.states
                    or row.captured_at != at or type(row.sequence) is not int or row.sequence <= self.sequence
                    or row.kind not in {"descriptor", "book", "terms", "outcome_view", "info_event", "coverage", "trade", "plugin_input"}
                    or digest(row.payload) != row.payload_sha256):
                raise ValueError("capture_binding")
            self.sequence = row.sequence
            validated.append(replace(row, payload=_freeze(dict(row.payload))))
        # Persist the invocation before application: missing applied ack is visible.
        self.tape.now = max(self.at or self.manifest.start, self.manifest.start)
        command = self.tape.artifact({"at": at, "rows": tuple(validated)})
        self.emit("command", operation="advance", artifact=command)
        try:
            self._drain_before(at)
            self._step(at, tuple(validated))
        except BaseException:
            self.stopped = True
            self.tape.abort()
            raise

    def _drain_before(self, at):
        while True:
            timers = [e.heap[0] for e in (self.engine, self.sensitivity) if e.heap]
            if self.next_minute < self.manifest.end:
                timers.append(self.next_minute)
            earlier = [t for t in timers if (self.at is None or t > self.at) and t < at]
            if not earlier:
                return
            self._step(min(earlier))

    def stop(self, at, reason="owner_stop"):
        if self.stopped:
            return None
        if not self.manifest.start <= at <= self.manifest.end or (self.at and at < self.at):
            raise ValueError("stop_clock")
        self.tape.now = self.at or self.manifest.start
        self.processing_at = at
        self.emit("command", operation="stop", at=at, reason=reason)
        # A stop does not call tick first: no HOLD/replacement after the request.
        if reason != "timer_deadline_missed":
            self._drain_before(at)
        self.tape.now = at
        self.at = at
        self.stopped = True
        for engine in (self.engine, self.sensitivity):
            for cid in sorted(engine.states):
                engine.latch(cid, at, reason)
        state = self.tape.artifact(self.state())
        self.emit("stopped", at=at, reason=reason, state=state, last_minute=self.last_minute)
        return self.tape.close(reason, state)

    def drill(self, at, injection):
        if self.manifest.mode != "drill" or injection not in ("kill", "cancel_all", "lost_ack", "gap"):
            raise ValueError("drill_not_admitted")
        if injection == "lost_ack":
            self.tape.now = at
            self.emit("ambiguous", at=at, reason="simulation_ack_missing",
                      state=self.tape.artifact(self.state()))
            self.stopped = True
            for engine in (self.engine, self.sensitivity):
                for state in engine.states.values():
                    state.legs = ()
            self.tape.abort()
            return None
        return self.stop(at, "drill_" + injection)
