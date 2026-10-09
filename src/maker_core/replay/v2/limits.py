"""Maker replay v2 input limits: bytes AND time, per pass and per run (owner decision 9, B-def D1).

The frozen reader (``maker_core.replay.bundle``) is not edited. Its ``Limits`` cap bytes at 70% of host
RAM, because v0.1 holds a whole bundle in memory, and its ``_Reader`` starts one clock at the first open.
``bundle_v02`` used to keep that reader for pass two, so every later ``records()`` re-read (the base passes,
then up to 12 matched-clock rounds) ran against the clock of the first open: a 16-date look of about
17,600 s fails at the frozen 14,400 s cap. v2 streams, so here:

- ``V2Limits`` bound one bundle: stored bytes (what is on disk, the E2 quantity), decoded bytes (the
  decompression-bomb bound, never held in memory), records, and the seconds of ONE pass over it.
- ``PassReader`` is created for pass one (``open_stream_bundle``) and again for every ``records()``
  call, so each pass or re-read gets its own clock. A pass never inherits an earlier pass's time.
- ``RunBudget`` is optional and shared by every bundle of one run: the run's wall-clock deadline
  (registration §8, 32,768 s) and its stored input total (§8, 16 GiB). It starts when it is built, and
  every pass of every bundle checks it, so a run cannot exceed its deadline through fresh pass clocks.
  Stored bytes are charged once per ``open_stream_bundle``; ``records()`` re-reads are not charged.
- Fail closed (X1 Defender M1): a bundle opened WITHOUT a ``RunBudget`` gets its own lifetime budget
  (``lifetime_budget``: the run deadline's default, 32,768 s from its open, and its own stored cap), held
  on the bundle and checked by every pass. Fresh pass clocks therefore never make re-reads unbounded.
  Looks and rehearsals (U2, U4) still pass ONE shared ``RunBudget`` for the whole run.

Every limit is explicit, positive and below a fixed ceiling; raising one never samples or truncates
input, it only widens what is admitted whole.
"""
from __future__ import annotations

from dataclasses import dataclass
import stat
import time

from maker_core.replay.bundle import (HOST_MAX_BYTES, HOST_MAX_RECORDS, HOST_MAX_SECONDS, BundleError, Limits,
                                      regular_path)

GIB = 1024**3
# Ceilings: an explicit limit above these is refused, never clipped.
CEILING_BUNDLE_STORED_BYTES = 16 * GIB
CEILING_BUNDLE_DECODED_BYTES = 64 * GIB
CEILING_BUNDLE_RECORDS = HOST_MAX_RECORDS
CEILING_PASS_SECONDS = HOST_MAX_SECONDS  # one pass over one bundle: the frozen host's four hours
CEILING_RUN_SECONDS = 32_768.0  # registration draft §8
CEILING_RUN_STORED_BYTES = 32 * GIB  # owner decision 8's fallback amendment: 2 GiB x 16 dates

# Defaults. E2 (1 GiB stored per date) is a gate, read from receipts; the reader's default admits up to
# the decision-8 fallback (2 GiB) so an over-E2 date is measured and then refused by the gate, not here.
DEFAULT_BUNDLE_STORED_BYTES = 2 * GIB
DEFAULT_BUNDLE_DECODED_BYTES = 16 * GIB
DEFAULT_BUNDLE_RECORDS = HOST_MAX_RECORDS
DEFAULT_PASS_SECONDS = 4_096.0  # twice E4's 2,048 s per date
DEFAULT_RUN_SECONDS = CEILING_RUN_SECONDS
DEFAULT_RUN_STORED_BYTES = 16 * GIB  # registration draft §8: input <= 16 GiB in total
# A bundle opened without a RunBudget: its whole life (every pass and re-read) fits one run's deadline.
DEFAULT_BUNDLE_LIFETIME_SECONDS = DEFAULT_RUN_SECONDS


def _positive_int(value, ceiling):
    if type(value) is not int or not 0 < value <= ceiling:
        raise BundleError("invalid_or_unbounded_limit")
    return value


def _positive_seconds(value, ceiling):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= ceiling:
        raise BundleError("invalid_time_limit")
    return value


@dataclass(frozen=True)
class V2Limits:
    """One bundle: stored and decoded bytes, records, and the seconds of one pass (pass one or a re-read)."""
    max_bundle_stored_bytes: int = DEFAULT_BUNDLE_STORED_BYTES
    max_bundle_decoded_bytes: int = DEFAULT_BUNDLE_DECODED_BYTES
    max_bundle_records: int = DEFAULT_BUNDLE_RECORDS
    max_pass_seconds: float = DEFAULT_PASS_SECONDS

    def __post_init__(self):
        _positive_int(self.max_bundle_stored_bytes, CEILING_BUNDLE_STORED_BYTES)
        _positive_int(self.max_bundle_decoded_bytes, CEILING_BUNDLE_DECODED_BYTES)
        _positive_int(self.max_bundle_records, CEILING_BUNDLE_RECORDS)
        _positive_seconds(self.max_pass_seconds, CEILING_PASS_SECONDS)

    def frozen(self) -> Limits:
        """The frozen v0.1 reader's ``Limits`` for a v0.1 bundle read through ``load_any``."""
        return Limits(min(self.max_bundle_stored_bytes, HOST_MAX_BYTES),
                      min(self.max_bundle_records, HOST_MAX_RECORDS),
                      min(self.max_pass_seconds, HOST_MAX_SECONDS))


def coerce(limits) -> V2Limits:
    """``None`` -> defaults; a frozen ``Limits`` keeps its meaning (its byte cap bounds stored AND decoded
    bytes, its time cap one pass); a ``V2Limits`` is used as given."""
    if limits is None:
        return V2Limits()
    if isinstance(limits, V2Limits):
        return limits
    if isinstance(limits, Limits):
        return V2Limits(limits.max_bytes, limits.max_bytes, limits.max_records, float(limits.max_seconds))
    raise BundleError("invalid_limits")


class RunBudget:
    """A whole run's deadline and stored-input total, shared by every bundle and every pass of the run."""

    def __init__(self, *, max_run_seconds: float = DEFAULT_RUN_SECONDS,
                 max_run_stored_bytes: int = DEFAULT_RUN_STORED_BYTES, clock=time.monotonic):
        self.max_run_seconds = _positive_seconds(max_run_seconds, CEILING_RUN_SECONDS)
        self.max_run_stored_bytes = _positive_int(max_run_stored_bytes, CEILING_RUN_STORED_BYTES)
        self.clock = clock
        self.started = clock()
        self.stored_bytes = 0

    def elapsed(self) -> float:
        return self.clock() - self.started

    def check(self):
        if self.elapsed() >= self.max_run_seconds:
            raise BundleError("run_time_cap")

    def charge(self, stored: int):
        if self.stored_bytes + stored > self.max_run_stored_bytes:
            raise BundleError("run_input_byte_cap")
        self.stored_bytes += stored


def lifetime_budget(limits: V2Limits, clock=time.monotonic) -> RunBudget:
    """The fail-closed fallback when no ``RunBudget`` is passed: one bundle's lifetime deadline, started at
    its open, with the bundle's own stored cap as the stored total (so it never binds tighter than V2Limits)."""
    return RunBudget(max_run_seconds=DEFAULT_BUNDLE_LIFETIME_SECONDS,
                     max_run_stored_bytes=limits.max_bundle_stored_bytes, clock=clock)


class PassReader:
    """One pass over one bundle: its own clock, plus the run's deadline when a ``RunBudget`` is given."""

    def __init__(self, limits: V2Limits, clock=time.monotonic, run: RunBudget | None = None):
        self.limits, self.clock, self.run = limits, clock, run
        self.started = clock()
        self.bytes_read = 0
        self.decoded_bytes = 0
        self.check()

    def check(self):
        if self.clock() - self.started >= self.limits.max_pass_seconds:
            raise BundleError("time_cap")
        if self.run is not None:
            self.run.check()

    def charge(self, stored: int):
        """Admit ``stored`` more bytes for this bundle (pass one only), before they are read."""
        if self.bytes_read + stored > self.limits.max_bundle_stored_bytes:
            raise BundleError("input_byte_cap_or_size_mismatch")
        if self.run is not None:
            self.run.charge(stored)
        self.bytes_read += stored

    def admit_decoded(self, decoded: int):
        """Admit a stream's declared decoded size against the bundle's decoded-byte cap."""
        if self.decoded_bytes + decoded > self.limits.max_bundle_decoded_bytes:
            raise BundleError("decoded_byte_cap")
        self.decoded_bytes += decoded

    def read(self, path, maximum: int) -> bytes:
        """A small whole file (the manifest), charged as stored bytes; refused if it changes while read."""
        self.check()
        path = regular_path(path)
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise BundleError("input_not_regular_file")
        if before.st_size > maximum:
            raise BundleError("input_byte_cap")
        self.charge(before.st_size)
        with path.open("rb") as handle:
            raw = handle.read(maximum + 1)
        after = path.stat()
        if len(raw) != before.st_size or (before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_ino, after.st_size, after.st_mtime_ns):
            raise BundleError("input_changed_during_read")
        self.check()
        return raw
