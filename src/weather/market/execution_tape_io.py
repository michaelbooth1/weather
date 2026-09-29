"""One lazy flusher for execution-tape files; status has a separate cadence."""

from __future__ import annotations

import os
import threading
import time
from typing import BinaryIO


class TapeFsyncBatch:
    """Flush Python buffers immediately and fsync each dirty file every second.

    Deadlines are monotonic and run even when the websocket is quiet. Rotation
    and orderly close are durability boundaries and force any outstanding sync.
    A background error is retained and raised by the next writer operation.
    """

    def __init__(self, *, start_worker: bool = True) -> None:
        self._condition = threading.Condition()
        self._pending: dict[BinaryIO, float] = {}
        self._errors: dict[BinaryIO, OSError] = {}
        self._worker: threading.Thread | None = None
        self._start_worker = start_worker

    def write(self, handle: BinaryIO, encoded: bytes) -> None:
        with self._condition:
            self._raise_error(handle)
            handle.write(encoded)
            handle.flush()
            if handle not in self._pending:
                now = time.monotonic()
                self._pending[handle] = now + 1.0
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

    def sync_due(self) -> None:
        with self._condition:
            now = time.monotonic()
            for handle, deadline in tuple(self._pending.items()):
                if now >= deadline:
                    try:
                        os.fsync(handle.fileno())
                    except OSError as exc:
                        self._errors[handle] = exc
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
                    os.fsync(handle.fileno())
            finally:
                self._pending.pop(handle, None)
                self._errors.pop(handle, None)
                handle.close()
                self._condition.notify()

    def _run(self) -> None:
        with self._condition:
            while self._pending:
                self.sync_due()
                if self._pending:
                    deadline = min(self._pending.values())
                    self._condition.wait(max(0.0, deadline - time.monotonic()))
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
