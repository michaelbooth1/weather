"""One lazy flusher for execution-tape files; status has a separate cadence."""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import BinaryIO

SYNC_INTERVAL_SECONDS = 1.0
# A transient fsync error is retried at the next deadlines; only a fault that
# persists this many consecutive attempts (about three seconds) fails closed.
MAX_SYNC_ATTEMPTS = 3


class TornAppendError(OSError):
    """A failed append left bytes on disk that could not be rolled back."""


def append_whole(handle: BinaryIO, encoded: bytes) -> None:
    """Append every byte of ``encoded`` or roll the file back to where it was.

    Raw handles may write short, so the loop finishes the row. On any error the
    partial row is truncated away, so a later restart never meets a torn tail.
    If the rollback itself fails, ``TornAppendError`` chains the original error
    and the handle must take no further rows.
    """

    start = handle.tell()
    try:
        written = handle.write(encoded)
        if written != len(encoded):
            view = memoryview(encoded)[written or 0:]
            while view:
                written = handle.write(view)
                if not written:
                    raise OSError("execution-tape append made no progress")
                view = view[written:]
        handle.flush()
    except BaseException as exc:
        try:
            handle.seek(start)
            handle.truncate()
        except BaseException as rollback:
            raise TornAppendError(f"could not roll back a partial row: {rollback}") from exc
        raise


class TapeFsyncBatch:
    """Append whole rows immediately and fsync each dirty file every second.

    Deadlines are monotonic and run even when the websocket is quiet. Rotation
    and orderly close are durability boundaries and force any outstanding sync.
    A background fsync error is retried at the next deadline; only after
    ``MAX_SYNC_ATTEMPTS`` consecutive failures is it retained and raised by the
    next writer operation.
    """

    def __init__(self, *, start_worker: bool = True) -> None:
        self._condition = threading.Condition()
        self._pending: dict[BinaryIO, float] = {}
        self._failures: dict[BinaryIO, int] = {}
        self._errors: dict[BinaryIO, OSError] = {}
        self._worker: threading.Thread | None = None
        self._start_worker = start_worker

    def write(self, handle: BinaryIO, encoded: bytes) -> None:
        with self._condition:
            self._raise_error(handle)
            try:
                append_whole(handle, encoded)
            except TornAppendError as exc:
                self._errors[handle] = exc
                raise
            if handle not in self._pending:
                now = time.monotonic()
                self._pending[handle] = now + SYNC_INTERVAL_SECONDS
                # After an idle period allow one second; during a burst retain
                # the original deadline instead of postponing on every row.
                self._condition.notify()
            if self._start_worker and self._worker is None:
                self._worker = threading.Thread(target=self._run, daemon=True,
                                                name="execution-tape-fsync")
                self._worker.start()

    def _raise_error(self, handle: BinaryIO) -> None:
        if handle in self._errors:
            raise self._errors[handle]

    def pending_count(self) -> int:
        with self._condition:
            return len(self._pending)

    def sync_due(self) -> None:
        with self._condition:
            now = time.monotonic()
            for handle, deadline in tuple(self._pending.items()):
                if now < deadline:
                    continue
                try:
                    os.fsync(handle.fileno())
                except OSError as exc:
                    failures = self._failures.get(handle, 0) + 1
                    if failures < MAX_SYNC_ATTEMPTS:
                        self._failures[handle] = failures
                        self._pending[handle] = now + SYNC_INTERVAL_SECONDS
                        print(f"execution-tape fsync attempt {failures} failed, retrying: {exc}",
                              file=sys.stderr, flush=True)
                        continue
                    self._errors[handle] = exc
                self._failures.pop(handle, None)
                del self._pending[handle]

    def check(self) -> None:
        with self._condition:
            if self._errors:
                raise next(iter(self._errors.values()))

    def close(self, handle: BinaryIO) -> None:
        with self._condition:
            try:
                self._raise_error(handle)
                if handle in self._pending:
                    for attempt in range(1, MAX_SYNC_ATTEMPTS + 1):
                        try:
                            os.fsync(handle.fileno())
                            break
                        except OSError:
                            if attempt == MAX_SYNC_ATTEMPTS:
                                raise
            finally:
                self._pending.pop(handle, None)
                self._failures.pop(handle, None)
                self._errors.pop(handle, None)
                handle.close()
                self._condition.notify()

    def _run(self) -> None:
        with self._condition:
            try:
                while self._pending:
                    self.sync_due()
                    if self._pending:
                        deadline = min(self._pending.values())
                        self._condition.wait(max(0.0, deadline - time.monotonic()))
            finally:
                # Any exit, including an unexpected error, lets the next write
                # start a fresh flusher instead of leaving rows unsynced.
                self._worker = None


TAPE_FSYNC = TapeFsyncBatch()


class StatusCadence:
    """Counters and timestamps coalesce; explicit state transitions bypass."""

    def __init__(self) -> None:
        self.last_write: float | None = None

    def due(self, *, force: bool) -> bool:
        TAPE_FSYNC.check()
        return force or self.last_write is None or time.monotonic() - self.last_write >= 10.0

    def written(self) -> None:
        self.last_write = time.monotonic()
