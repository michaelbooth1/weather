import json
import itertools
import shutil
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


def test_status_coalesces_frames_but_publishes_transitions(tmp_path, monkeypatch, clock_and_batch):
    clock, _ = clock_and_batch
    writes = []
    original = tape.write_json_atomic

    def record(path, payload, **kwargs):
        writes.append(path)
        return original(path, payload, **kwargs)

    monkeypatch.setattr(tape, "write_json_atomic", record)
    with tape.ExecutionTapeCoordinator((SEED,), snapshots_root=tmp_path, now=START) as coordinator:
        coordinator.mark_connected((SEED.key,), session_id="s", at=START)
        writes.clear()
        for tick in range(1, 1000):
            clock[0] = tick / 100
            at = START + timedelta(seconds=clock[0])
            coordinator.heartbeat((SEED.key,), at=at, message_seen=True)
            coordinator.ingest_frame(ROW, session_id="s", received_at=at)
        assert writes == []
        clock[0] = 10
        coordinator.heartbeat((SEED.key,), at=START + timedelta(seconds=10))
        assert writes == [coordinator.stores[SEED.key].status_path, coordinator.status_path]
        persisted = json.loads(coordinator.status_path.read_text())
        assert persisted["last_counted"]["trades_written"] == 999
        assert persisted.keys() == coordinator.status_payload(now=START).keys()
        coordinator.mark_disconnected((SEED.key,), session_id="s", at=START,
                                      reason="fixture disconnect")
        assert len(writes) == 4
        coordinator.set_seed_error("fixture seed error", now=START)
        assert len(writes) == 6
        coordinator.stop(now=START)
        assert json.loads(coordinator.status_path.read_text())["state"] == "STOPPED"


def test_grouped_fsync_idle_file_rotation_and_identical_bytes(tmp_path, monkeypatch, clock_and_batch):
    clock, batch = clock_and_batch
    synced = []
    monkeypatch.setattr(io.os, "fsync", lambda fd: synced.append((fd, clock[0])))
    writer = tape.RotatingJsonlWriter(tmp_path, "rows", max_part_bytes=100)
    expected = []
    for i in range(4):
        row = {"i": i}
        expected.append(tape.canonical_json_bytes(row) + b"\n")
        writer.append(row)
        clock[0] += 0.2
        batch.sync_due()
    assert synced == []
    assert (tmp_path / "rows-00000.jsonl").read_bytes() == b"".join(expected)
    clock[0] = 1.0
    batch.sync_due()  # final row syncs without another append
    assert len(synced) == 1
    writer.append({"i": 4})
    writer.append({"i": 5})
    assert len(synced) == 1
    writer.close()
    assert len(synced) == 2
    writer = tape.RotatingJsonlWriter(tmp_path / "rotation", "rows", max_part_bytes=10)
    writer.append({"i": 0})
    writer.append({"i": 1})
    assert len(synced) == 3  # old part durable before rotation
    writer.close()
    assert len(synced) == 4


def test_background_sync_runs_without_new_frames(tmp_path, monkeypatch):
    synced = threading.Event()
    monkeypatch.setattr(io.os, "fsync", lambda fd: synced.set())
    batch = io.TapeFsyncBatch()
    handle = (tmp_path / "idle.jsonl").open("ab")
    try:
        batch.write(handle, b'{}\n')
        assert synced.wait(3), "idle row did not reach the background sync"
    finally:
        batch.close(handle)


@pytest.mark.parametrize("lose_last_second", [False, True])
def test_crash_restart_replays_physical_tail_with_stale_status(tmp_path, clock_and_batch, lose_last_second):
    clock, batch = clock_and_batch
    live = tmp_path / "live"
    crash = tmp_path / "crash"
    with tape.ExecutionTapeCoordinator((SEED,), snapshots_root=live, now=START) as coordinator:
        coordinator.mark_connected((SEED.key,), session_id="s", at=START)
        coordinator.ingest_frame(ROW, session_id="s", received_at=START)
        clock[0] = 1
        batch.sync_due()
        trade_path = coordinator.stores[SEED.key].trades.parts[0]["path"]
        durable_bytes = trade_path.read_bytes()
        coordinator.ingest_frame(ROW, session_id="s", received_at=START + timedelta(seconds=1))
        # Copy the OS-visible files before orderly close, omitting the live lease.
        shutil.copytree(live, crash, ignore=shutil.ignore_patterns("*.writer.lock"))
        if lose_last_second:
            (crash / "fixture/execution_tape/trades-00000.jsonl").write_bytes(durable_bytes)
            (crash / "fixture/execution_tape/dedupe-00000.jsonl").write_bytes(b"")
    with tape.ExecutionTapeCoordinator((SEED,), snapshots_root=crash,
                                      now=START + timedelta(seconds=2)) as restarted:
        store = restarted.stores[SEED.key]
        assert store.state["trades_written"] == (1 if lose_last_second else 2)
        assert store.state["connection_state"] == "DISCONNECTED"
        assert store.state["last_error"]


def test_persistent_fsync_failure_surfaces_on_capture_and_close(tmp_path, monkeypatch, clock_and_batch):
    clock, batch = clock_and_batch
    writer = tape.RotatingJsonlWriter(tmp_path, "rows")
    writer.append({"i": 0})

    def fail(fd):
        raise OSError("fixture storage failure")

    monkeypatch.setattr(io.os, "fsync", fail)
    for attempt in range(1, io.MAX_SYNC_ATTEMPTS + 1):  # transient faults retry first
        clock[0] = attempt
        batch.sync_due()
    with pytest.raises(OSError, match="fixture storage failure"):
        writer.append({"i": 1})
    with pytest.raises(OSError, match="fixture storage failure"):
        writer.close()


def test_torn_crash_tail_remains_fail_closed(tmp_path):
    (tmp_path / "rows-00000.jsonl").write_bytes(b'{"i":0}\n{"i":')
    with pytest.raises(tape.ExecutionTapeError, match="unterminated"):
        tape.RotatingJsonlWriter(tmp_path, "rows")


def test_all_tape_bytes_match_per_row_fsync_reference(tmp_path, monkeypatch, clock_and_batch):
    _, batch = clock_and_batch
    original_write = batch.write

    def old_write(handle, encoded):
        handle.write(encoded)
        handle.flush()
        io.os.fsync(handle.fileno())

    def capture(write):
        monkeypatch.setattr(batch, "write", write)
        identities = itertools.count()
        monkeypatch.setattr(tape.uuid, "uuid4", lambda: SimpleNamespace(hex=f"{next(identities):032x}"))
        with tape.ExecutionTapeCoordinator((SEED,), snapshots_root=tmp_path, now=START,
                                          max_part_bytes=4096) as coordinator:
            coordinator.begin_connecting((SEED.key,), session_id="s", at=START)
            coordinator.mark_connected((SEED.key,), session_id="s", at=START)
            for i in range(8):
                coordinator.ingest_frame(ROW, session_id="s", received_at=START + timedelta(milliseconds=i))
            coordinator.ingest_frame("invalid", session_id="s", received_at=START)
            coordinator.stop(now=START + timedelta(seconds=2))
        return {str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*.jsonl")}

    reference = capture(old_write)
    for child in tmp_path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    assert capture(original_write) == reference


def test_crash_replays_rejections_and_publishes_degradation_immediately(tmp_path, clock_and_batch):
    with tape.ExecutionTapeCoordinator((SEED,), snapshots_root=tmp_path, now=START) as coordinator:
        coordinator.mark_connected((SEED.key,), session_id="s", at=START)
        coordinator.ingest_frame("invalid", session_id="s", received_at=START)
        assert json.loads(coordinator.status_path.read_text())["state"] == "DEGRADED_EVIDENCE_LOSS"
        coordinator.ingest_frame("invalid", session_id="s", received_at=START)
        cached = json.loads(coordinator.status_path.read_text())
        assert cached["parse_rejections"] == 1
    # Emulate the root status having survived only through the first rejection.
    (tmp_path / "execution_tape_status.json").write_text(json.dumps(cached))
    with tape.ExecutionTapeCoordinator((SEED,), snapshots_root=tmp_path, now=START) as restarted:
        assert restarted.state["parse_rejections"] == 2
