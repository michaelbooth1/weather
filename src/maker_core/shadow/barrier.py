"""The live loop's logical-time barrier: one queue, channel watermarks, engine-order drain, lateness bounds.

Spec: D-shadow-gate-spec-v3 §4.5 (M4), kept by v3.1 and v3.2; Tier L row L6 (v3 §4.4: "the same barrier and
lateness bounds"); verdict reasons ``INCOMPLETE (live_lateness)`` and ``INCOMPLETE (late_records)`` (v3 §10);
controls Kx1 and Kx3 (v3 §7) and mutants MB1, MB2 (v3 §15). v3 §14 places the barrier in the live adapter
(``maker_core.shadow.live_kernel``), which does not exist on this branch; this module is the barrier on its own,
for that adapter to consume.

Contract (v3 §4.5):
- **One queue.** Every input is enqueued with its logical instant: book read completions, websocket market
  messages, reward replies, view computations, observation replies and timer due instants. The receipt instant is
  stamped by the receiving thread (``received_at``, or this barrier's wall clock when omitted). Only the Kernel
  thread drains.
- **Watermarks.** Channel ``c`` has ``W_c``, the latest receipt instant it has delivered. The websocket channel
  also advances with each ping/pong (``advance``); a polled channel advances at each poll completion. ``W = min_c
  W_c``; a channel that has delivered nothing holds ``W`` at "none".
- **Drain rule.** Instant ``t`` is processed only when ``W >= t``. Its records are delivered in engine order
  (``engine.py:132-161`` on the build line): prints (``kind == "trade"``) first, then the other records by enqueue
  sequence; only then the timers due at ``t`` (by schedule sequence). The consumer then wakes conditions in
  condition-id order, as the engine does.
- **Late records.** A record whose receipt instant is at or before an instant already processed is ingested at the
  current logical instant, keeps its original receipt (``received_at``) and is counted ``late_restamped``. Reading
  of "current logical instant" used here: the earliest unprocessed instant, ``last processed + 1 µs``, so logical
  instants stay strictly increasing (the engine refuses ``instant_order``). More than 1 % late records in a day ->
  ``late_records``.
- **Lateness bounds.** Decision lateness = wall time at ``decide()`` - logical instant; timer lateness = wall time at
  fire - due instant. Per UTC day, p99 <= 1 s and max <= 5 s for both, else ``live_lateness``.

Domain-neutral and pure: no I/O, no venue or ``weather`` import. Thread-safe enqueue; a single drainer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from threading import Lock

TRADE = "trade"
RESTAMP_STEP = timedelta(microseconds=1)
LATENESS_P99_SECONDS = 1.0  # v3 §4.5
LATENESS_MAX_SECONDS = 5.0  # v3 §4.5
LATE_RECORD_FRACTION = 0.01  # v3 §4.5: more than 1 % -> INCOMPLETE (late_records)
LIVE_LATENESS = "live_lateness"
LATE_RECORDS = "late_records"


def _utc(value, name):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name}_must_be_utc")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class QueuedRecord:
    """A queued input. ``at`` is its logical instant; ``received_at`` its original receipt instant."""

    at: datetime
    received_at: datetime
    channel: str
    kind: str
    condition_id: str | None
    payload: object
    sequence: int
    restamped: bool = False


@dataclass(frozen=True)
class Timer:
    at: datetime
    condition_id: str | None
    kind: str
    sequence: int


@dataclass(frozen=True)
class DrainedInstant:
    """One logical instant, in engine order: ``trades``, then ``records``, then ``timers``."""

    at: datetime
    trades: tuple
    records: tuple
    timers: tuple

    def steps(self):
        """The delivery order the Kernel must apply (Kx1/Kx3 are violations of exactly this order)."""
        return (*(("trade", r) for r in self.trades), *(("record", r) for r in self.records),
                *(("timer", t) for t in self.timers))


class LogicalTimeBarrier:
    def __init__(self, channels, *, wall_clock):
        channels = tuple(channels)
        if not channels or len(set(channels)) != len(channels):
            raise ValueError("barrier_channels_required")
        self.wall_clock = wall_clock
        self._lock = Lock()
        self._watermarks = {channel: None for channel in channels}
        self._records, self._timers = [], []
        self._sequence = 0
        self.last_processed = None
        self._day = {}  # utc date -> counters and lateness samples

    # -- producers (any thread) -----------------------------------------------------------------------------------
    def enqueue(self, channel, kind, *, condition_id=None, payload=None, received_at=None):
        received_at = _utc(received_at if received_at is not None else self.wall_clock(), "received_at")
        with self._lock:
            self._check_channel(channel)
            self._advance(channel, received_at)
            at, restamped = received_at, False
            if self.last_processed is not None and received_at <= self.last_processed:
                at, restamped = self.last_processed + RESTAMP_STEP, True
            record = QueuedRecord(at, received_at, channel, kind, condition_id, payload, self._next(), restamped)
            self._records.append(record)
            day = self._stats(at)
            day["records"] += 1
            day["late_restamped"] += restamped
            return record

    def advance(self, channel, instant):
        """A ping/pong (websocket) or a poll completion (polled channel) moves ``W_c`` without a record."""
        instant = _utc(instant, "watermark")
        with self._lock:
            self._check_channel(channel)
            self._advance(channel, instant)

    # -- the Kernel thread ----------------------------------------------------------------------------------------
    def schedule_timer(self, at, *, condition_id=None, kind="timer"):
        at = _utc(at, "timer_at")
        with self._lock:
            if self.last_processed is not None and at <= self.last_processed:
                raise ValueError("timer_not_after_processed_instant")
            timer = Timer(at, condition_id, kind, self._next())
            self._timers.append(timer)
            return timer

    def watermark(self):
        with self._lock:
            return self._global()

    def watermark_lags(self, now=None):
        """Per-channel watermark lag in seconds (the ``clock`` row field, v3 §4.6); None before first delivery."""
        now = _utc(now if now is not None else self.wall_clock(), "now")
        with self._lock:
            return {c: None if w is None else (now - w).total_seconds() for c, w in self._watermarks.items()}

    def pop_ready(self):
        """The next instant with ``t <= W``, in engine order, or None. Re-evaluated per call, so timers the Kernel
        schedules while handling an instant are seen by the next call."""
        with self._lock:
            limit = self._global()
            if limit is None:
                return None
            pending = [r.at for r in self._records] + [t.at for t in self._timers]
            ready = [at for at in pending if at <= limit]
            if not ready:
                return None
            at = min(ready)
            items = [r for r in self._records if r.at == at]
            timers = [t for t in self._timers if t.at == at]
            self._records = [r for r in self._records if r.at != at]
            self._timers = [t for t in self._timers if t.at != at]
            self.last_processed = at
            return self._instant(at, items, timers)

    def drain(self):
        while (instant := self.pop_ready()) is not None:
            yield instant

    def _instant(self, at, items, timers):
        """Engine order: prints first, then other records by enqueue sequence, then timers by schedule sequence."""
        items = sorted(items, key=lambda r: r.sequence)
        return DrainedInstant(at, tuple(r for r in items if r.kind == TRADE),
                              tuple(r for r in items if r.kind != TRADE),
                              tuple(sorted(timers, key=lambda t: t.sequence)))

    # -- lateness (v3 §4.5) ---------------------------------------------------------------------------------------
    def note_decision(self, at, wall=None):
        """Record decision lateness: wall time at ``decide()`` minus the logical instant."""
        return self._note("decision", at, wall)

    def note_timer_fired(self, due, wall=None):
        """Record timer lateness: wall time at fire minus the due instant."""
        return self._note("timer", due, wall)

    def day_report(self, day):
        """``timing.lateness``, ``late_restamped`` and the INCOMPLETE reasons for one UTC day (v3 §4.5, §10, §13)."""
        with self._lock:
            stats = self._day.get(day) or self._empty()
            report = {"records": stats["records"], "late_restamped": stats["late_restamped"]}
            for kind in ("decision", "timer"):
                samples = sorted(stats[kind])
                report[f"{kind}_p99"] = _p99(samples)
                report[f"{kind}_max"] = samples[-1] if samples else 0.0
        reasons = []
        if any(report[f"{k}_p99"] > LATENESS_P99_SECONDS or report[f"{k}_max"] > LATENESS_MAX_SECONDS
               for k in ("decision", "timer")):
            reasons.append(LIVE_LATENESS)
        if report["records"] and report["late_restamped"] / report["records"] > LATE_RECORD_FRACTION:
            reasons.append(LATE_RECORDS)
        report["incomplete"] = reasons
        return report

    # -- internals ------------------------------------------------------------------------------------------------
    def _note(self, kind, at, wall):
        at = _utc(at, "logical_instant")
        wall = _utc(wall if wall is not None else self.wall_clock(), "wall")
        lateness = (wall - at).total_seconds()
        with self._lock:
            self._stats(at)[kind].append(lateness)
        return lateness

    def _check_channel(self, channel):
        if channel not in self._watermarks:
            raise ValueError("unknown_channel")

    def _advance(self, channel, instant):
        current = self._watermarks[channel]
        if current is None or instant > current:
            self._watermarks[channel] = instant

    def _global(self):
        values = list(self._watermarks.values())
        return None if any(v is None for v in values) else min(values)

    def _next(self):
        self._sequence += 1
        return self._sequence

    @staticmethod
    def _empty():
        return {"records": 0, "late_restamped": 0, "decision": [], "timer": []}

    def _stats(self, at):
        return self._day.setdefault(at.date(), self._empty())


def _p99(samples):
    """Nearest-rank 99th percentile of sorted samples; 0.0 when there are none."""
    if not samples:
        return 0.0
    return samples[max(0, math.ceil(0.99 * len(samples)) - 1)]


__all__ = ["DrainedInstant", "LATE_RECORDS", "LIVE_LATENESS", "LogicalTimeBarrier", "QueuedRecord", "Timer"]
