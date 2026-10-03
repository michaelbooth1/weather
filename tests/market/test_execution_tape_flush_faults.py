"""Execution-tape write-path faults: transient fsync errors and torn appends.

A single transient background fsync error used to be retained until the handle
closed and re-raised by every status write, freezing the capture heartbeat
until the supervisor's stale restart (3-4 minutes of capture lost).
"""

import io as stdio
import json
import threading
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from weather.market import execution_tape_io as io
from weather.market import execution_tape_store as tape


START = datetime(2026, 8, 1, tzinfo=timezone.utc)
ROW = {"event_type": "last_trade_price", "asset_id": "123",
       "market": "0x" + "a" * 64, "price": "0.5", "size": "2",
       "side": "BUY", "timestamp": "1785542400000"}
SEED = tape.MarketDaySeed(market_id="toronto", target_date=date(2026, 8, 1),
                         event_slug="fixture", asset_ids=("123",),
                         condition_ids=(ROW["market"],), source="fixture")


@pytest.fixture
def clock_and_batch(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(io, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    batch = io.TapeFsyncBatch(start_worker=False)
    monkeypatch.setattr(io, "TAPE_FSYNC", batch)
    monkeypatch.setattr(tape, "TAPE_FSYNC", batch)
    return clock, batch


def _fsync_failing(times):
    calls = {"failed": 0, "synced": 0}

    def fsync(fd):
        if times is None or calls["failed"] < times:
            calls["failed"] += 1
            raise OSError("fixture transient storage failure")
        calls["synced"] += 1

    return calls, fsync


def test_transient_fsync_failure_keeps_capture_heartbeat_live(tmp_path, monkeypatch, clock_and_batch):
    clock, batch = clock_and_batch
    calls, fsync = _fsync_failing(1)
    monkeypatch.setattr(io.os, "fsync", fsync)
    with tape.ExecutionTapeCoordinator((SEED,), snapshots_root=tmp_path, now=START) as coordinator:
        coordinator.mark_connected((SEED.key,), session_id="s", at=START)
        coordinator.ingest_frame(ROW, session_id="s", received_at=START)
        clock[0] = 1
        batch.sync_due()  # the one transient failure
        assert calls["failed"] == 1 and batch.pending_count() == 1  # only the failed file waits
        clock[0] = 10
        at = START + timedelta(seconds=10)
        coordinator.ingest_frame(ROW, session_id="s", received_at=at)
        coordinator.heartbeat((SEED.key,), at=at, message_seen=True)  # raised here before the fix
        persisted = json.loads(coordinator.status_path.read_text())
        assert persisted["updated_at_utc"] == at.isoformat()  # supervisor heartbeat fallback
        assert persisted["last_counted"]["trades_written"] == 2
        synced_before_retry = calls["synced"]
        batch.sync_due()  # the retry covers both rows of the failed file
        assert calls["synced"] > synced_before_retry
        clock[0] = 11
        batch.sync_due()
        assert batch.pending_count() == 0
        batch.check()


def test_persistent_fsync_failure_fails_closed_after_bounded_retries(tmp_path, monkeypatch, clock_and_batch):
    clock, batch = clock_and_batch
    calls, fsync = _fsync_failing(None)
    monkeypatch.setattr(io.os, "fsync", fsync)
    writer = tape.RotatingJsonlWriter(tmp_path, "rows")
    writer.append({"i": 0})
    for attempt in range(1, io.MAX_SYNC_ATTEMPTS):
        clock[0] = attempt
        batch.sync_due()
        writer.append({"i": attempt})  # still accepted inside the bound
        batch.check()
    clock[0] = io.MAX_SYNC_ATTEMPTS
    batch.sync_due()
    assert calls["failed"] == io.MAX_SYNC_ATTEMPTS
    with pytest.raises(OSError, match="transient storage failure"):
        batch.check()
    with pytest.raises(OSError, match="transient storage failure"):
        writer.append({"i": 99})
    with pytest.raises(OSError, match="transient storage failure"):
        writer.close()


class _TornRaw(stdio.FileIO):
    """When armed, writes half of one request and then fails like storage."""

    armed = None

    def write(self, data):
        if _TornRaw.armed == "fail":
            raise OSError("fixture write failure")
        if _TornRaw.armed == "half":
            _TornRaw.armed = "fail"
            return super().write(bytes(data)[: len(data) // 2])
        return super().write(data)


class _FaultPath(type(tape.Path())):
    """Routes the writer's own append handle through ``_TornRaw``."""

    def open(self, mode="r", buffering=-1, *args, **kwargs):
        if mode == "ab":
            raw = _TornRaw(self, "ab")
            return raw if buffering == 0 else stdio.BufferedWriter(raw)
        return super().open(mode, buffering, *args, **kwargs)


def test_failed_append_rolls_back_torn_row_so_restart_is_clean(tmp_path, monkeypatch, clock_and_batch):
    _TornRaw.armed = None
    original_path = tape.Path
    monkeypatch.setattr(tape, "Path", _FaultPath)
    writer = tape.RotatingJsonlWriter(tmp_path, "rows")
    writer.append({"i": 0})
    _TornRaw.armed = "half"
    with pytest.raises(OSError, match="fixture write failure"):
        writer.append({"i": 1, "pad": "x" * 64})
    _TornRaw.armed = None
    path = tmp_path / "rows-00000.jsonl"
    # A stale restart sees only OS-visible bytes: they must still be whole rows.
    assert path.read_bytes() == b'{"i":0}\n'
    monkeypatch.setattr(tape, "Path", original_path)
    reopened = tape.RotatingJsonlWriter(tmp_path, "rows")
    assert reopened.stats()["row_count"] == 1
    reopened.close()
    writer.append({"i": 2})  # the live writer also stays usable
    writer.close()
    assert path.read_bytes() == b'{"i":0}\n{"i":2}\n'


class _ShortRaw(stdio.FileIO):
    def write(self, data):
        return super().write(bytes(data)[:3])


def test_short_raw_writes_still_append_whole_rows(tmp_path, clock_and_batch):
    _, batch = clock_and_batch
    path = tmp_path / "rows-00000.jsonl"
    handle = _ShortRaw(path, "ab")
    batch.write(handle, b'{"i":0}\n')
    batch.write(handle, b'{"i":1}\n')
    batch.close(handle)
    assert path.read_bytes() == b'{"i":0}\n{"i":1}\n'


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_flusher_thread_restarts_after_unexpected_error(tmp_path, monkeypatch):
    synced = threading.Event()
    calls = []

    def fsync(fd):
        calls.append(fd)
        if len(calls) == 1:
            raise RuntimeError("fixture flusher bug")
        synced.set()

    monkeypatch.setattr(io.os, "fsync", fsync)
    batch = io.TapeFsyncBatch()
    handle = (tmp_path / "rows.jsonl").open("ab", buffering=0)
    try:
        batch.write(handle, b"{}\n")
        deadline = threading.Event()
        for _ in range(60):
            if calls and batch._worker is None:
                break
            deadline.wait(0.1)
        assert calls and batch._worker is None, "dead flusher left a stale worker reference"
        batch.write(handle, b"{}\n")
        assert synced.wait(3), "pending row was never synced after a flusher error"
    finally:
        batch.close(handle)
