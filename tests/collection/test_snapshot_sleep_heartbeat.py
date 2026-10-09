"""Snapshot loop keeps its liveness heartbeat fresh while idling between iterations.

Guards: storage capture admission heartbeat bound
(replay_cache_compression_admission.MAX_HEARTBEAT_AGE_SECONDS = 180 s, used by
check_capture_health) against the snapshot loop's ~290 s idle sleep; incident:
91a cold-snapshot nightly FAILED_RETAIN_AND_INSPECT on capture_unhealthy:snapshot.
Also guards that idle heartbeats never touch the error latch, the iteration
outcome, the pause flag or process identity, and that pause/stop/triggered-work
handling during the sleep is unchanged.
"""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import weather.collection.snapshot_tracker as tracker
from weather.collection.triggered_snapshot_queue import enqueue_triggered_snapshot
from weather.operations.capture_resource_gate import CaptureLoopSpec, inspect_capture_loop
from weather.operations.replay_cache_compression_admission import (
    MAX_HEARTBEAT_AGE_SECONDS,
    check_capture_health,
)


# 06:00 UTC is 02:00 America/Toronto: inside the 00:30-09:00 storage window and
# outside the 04:45-06:45 tiering reservation, so only loop health can BLOCK.
START = datetime(2026, 7, 14, 6, 0, tzinfo=timezone.utc)
BATCH_SECONDS = 12
NEXT_DUE_SECONDS = 300  # host shape: ~300 s cycle, ~288 s idle sleep
GIB = 1024**3


class Clock:
    def __init__(self, start=START):
        self.current = start

    def now(self):
        return self.current

    def advance(self, seconds):
        self.current = self.current + timedelta(seconds=seconds)


class NoopPower:
    def start(self):
        return {"status": "synthetic"}

    def stop(self):
        return None


def _patch_loop(monkeypatch, tmp_path, clock, *, market_ids=("toronto",), batch_error=None):
    specs = [SimpleNamespace(id=market_id) for market_id in market_ids]
    monkeypatch.setattr(tracker, "LOOP_STATUS_PATH", tmp_path / "loop_status.json")
    monkeypatch.setattr(tracker, "DIAGNOSTICS_PATH", tmp_path / "diagnostics.jsonl")
    monkeypatch.setattr(tracker, "PAUSE_FLAG_PATH", tmp_path / "pause.flag")
    monkeypatch.setattr(tracker, "all_specs", lambda: specs)

    def due_rows(*_args, **_kwargs):
        return [
            (spec, {
                "market_id": spec.id,
                "event_slug": f"event-{spec.id}",
                "target_date": "2026-07-14",
                "due": True,
                "last_snapshot_at": (clock.now() - timedelta(minutes=10)).isoformat(),
                "next_due_at": clock.now().isoformat(),
            })
            for spec in specs
        ]

    batches = []

    def fake_batch(requests, **_kwargs):
        started = clock.now()
        batches.append(started)
        clock.advance(BATCH_SECONDS)
        records = []
        for row in requests:
            if batch_error and row["market_id"] == batch_error:
                result = {"written": False, "error": "capture_timeout: synthetic"}
            else:
                result = {
                    "written": True,
                    "snapshot_id": f"{row['market_id']}-{len(batches)}",
                    "next_due_at": (started + timedelta(seconds=NEXT_DUE_SECONDS)).isoformat(),
                }
            records.append({
                "market_id": row["market_id"],
                "started_at": started,
                "completed_at": clock.now(),
                "result": result,
                "execution": {"mode": "synthetic_isolated"},
            })
        return {"records": records, "summary": {"mode": "isolated_subprocess_batch"}}

    monkeypatch.setattr(tracker, "ordered_snapshot_specs", due_rows)
    monkeypatch.setattr(tracker, "run_bounded_capture_batch", fake_batch)
    monkeypatch.setattr(
        tracker,
        "runtime_identity_status",
        lambda *_args, **_kwargs: {"runtime_code_state": "current_code"},
    )
    monkeypatch.setattr(
        tracker,
        "current_fleet_collection_health",
        lambda **_kwargs: {"summary": {}, "markets": []},
    )
    monkeypatch.setattr(tracker, "keep_system_awake", lambda _reason: NoopPower())
    return batches


def _record_writes(monkeypatch):
    writes = []
    original = tracker.write_loop_status

    def recording_write(status):
        writes.append(json.loads(json.dumps(status, default=str)))
        return original(status)

    monkeypatch.setattr(tracker, "write_loop_status", recording_write)
    return writes


def _age_seconds(now, stamp):
    if not stamp:
        return None
    return (now - datetime.fromisoformat(stamp)).total_seconds()


def _healthy_peer(name):
    return {
        "name": name,
        "active": True,
        "degraded": False,
        "heartbeat_fresh": True,
        "pid_agreement": True,
        "process_identity_matches_lock": True,
        "heartbeat_age_seconds": 5.0,
        "process_diagnostics": {"status_pid_alive": True, "lock_pid_alive": True},
    }


def _admission_at(now, status_path):
    """Evaluate check_capture_health exactly as observe_capture_admission feeds it."""

    status = json.loads(status_path.read_text(encoding="utf-8"))
    row = inspect_capture_loop(
        CaptureLoopSpec("snapshot", status_path, 600.0),
        now=now,
        process_checker=lambda _pid: True,
    )
    if type(status.get("consecutive_errors")) is not int or status["consecutive_errors"] != 0 \
            or status.get("paused") is not False:
        row["degraded"] = True
    # Process identity is not under test here; the synthetic loop runs in-process.
    row["process_identity_matches_lock"] = True
    row["heartbeat_age_seconds"] = _age_seconds(now, status.get("last_heartbeat"))
    row["last_clean_iteration_age_seconds"] = _age_seconds(now, status.get("last_clean_iteration_at"))
    result = check_capture_health(
        now=now,
        available=8 * GIB,
        commit=10.0,
        loops=[row, _healthy_peer("clob"), _healthy_peer("observation_trigger")],
    )
    return result, row


def test_full_idle_sleep_never_ages_heartbeat_past_storage_admission(tmp_path, monkeypatch):
    clock = Clock()
    _patch_loop(monkeypatch, tmp_path, clock)
    status_path = tmp_path / "loop_status.json"
    evaluated = []

    def sleep_fn(seconds):
        # Advance the fake clock one second at a time and run the admission
        # check after every second of the idle sleep.
        whole, fraction = divmod(float(seconds), 1.0)
        for _ in range(int(whole)):
            clock.advance(1)
            evaluated.append((clock.now(), *_admission_at(clock.now(), status_path)))
        if fraction:
            clock.advance(fraction)

    status = tracker.run_loop(
        interval_minutes=10,
        max_iterations=2,
        sleep_fn=sleep_fn,
        now_fn=clock.now,
        available_memory_fn=lambda: 16 * GIB,
        trigger_queue_root=tmp_path / "trigger_queue",
    )

    assert status["iterations"] == 2
    assert status["last_iteration_outcome"] == "clean"
    # The whole host-shaped idle sleep was evaluated second by second.
    assert len(evaluated) == NEXT_DUE_SECONDS - BATCH_SECONDS
    blocked = [
        (when.isoformat(), row["heartbeat_age_seconds"], result["reasons"])
        for when, result, row in evaluated
        if result["status"] != "PASS"
    ]
    assert blocked == []
    ages = [row["heartbeat_age_seconds"] for _when, _result, row in evaluated]
    assert max(ages) <= tracker.SLEEP_HEARTBEAT_SECONDS
    assert max(ages) < MAX_HEARTBEAT_AGE_SECONDS


def test_sleep_heartbeats_change_only_the_heartbeat_and_keep_the_error_latch(
    tmp_path,
    monkeypatch,
):
    clock = Clock()
    _patch_loop(monkeypatch, tmp_path, clock, market_ids=("toronto", "broken"), batch_error="broken")
    writes = _record_writes(monkeypatch)
    sleep_plan_index = {}

    def sleep_fn(seconds):
        sleep_plan_index.setdefault("index", len(writes) - 1)
        clock.advance(seconds)

    tracker.run_loop(
        interval_minutes=10,
        max_iterations=2,
        sleep_fn=sleep_fn,
        now_fn=clock.now,
        available_memory_fn=lambda: 16 * GIB,
        trigger_queue_root=tmp_path / "trigger_queue",
    )

    plan_write = writes[sleep_plan_index["index"]]
    assert plan_write["iterations"] == 1
    assert plan_write["consecutive_errors"] == 1
    assert plan_write["last_iteration_outcome"] == "error"
    assert plan_write["last_sleep_seconds"] == NEXT_DUE_SECONDS - BATCH_SECONDS
    sleep_writes = [
        write for write in writes[sleep_plan_index["index"] + 1:] if write["iterations"] == 1
    ]
    # 288 s idle at a 60 s cadence: beats at 60/120/180/240, none after the last chunk.
    assert len(sleep_writes) == 4
    expected = {key: value for key, value in plan_write.items() if key != "last_heartbeat"}
    previous = datetime.fromisoformat(plan_write["last_heartbeat"])
    for write in sleep_writes:
        assert {key: value for key, value in write.items() if key != "last_heartbeat"} == expected
        beat = datetime.fromisoformat(write["last_heartbeat"])
        assert (beat - previous).total_seconds() == tracker.SLEEP_HEARTBEAT_SECONDS
        previous = beat
    # The second iteration then latches a second consecutive error as before.
    assert writes[-1]["iterations"] == 2
    assert writes[-1]["consecutive_errors"] == 2


def test_inline_override_sleep_also_beats_without_clearing_the_error_latch(tmp_path, monkeypatch):
    clock = Clock()
    calls = {"count": 0}
    seen_during_sleep = []
    status_path = tmp_path / "loop_status.json"

    def capture_fn(force=False, market_id="toronto"):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("restart warm-up failed")
        return {"written": True, "snapshot_id": f"{market_id}-recovered"}

    def sleep_fn(seconds):
        clock.advance(seconds)
        seen_during_sleep.append(json.loads(status_path.read_text(encoding="utf-8")))

    monkeypatch.setattr(tracker, "LOOP_STATUS_PATH", status_path)
    monkeypatch.setattr(tracker, "DIAGNOSTICS_PATH", tmp_path / "diagnostics.jsonl")
    monkeypatch.setattr(tracker, "PAUSE_FLAG_PATH", tmp_path / "pause.flag")
    monkeypatch.setattr(tracker, "all_specs", lambda: [SimpleNamespace(id="toronto")])
    monkeypatch.setattr(
        tracker,
        "current_fleet_collection_health",
        lambda **_kwargs: {"summary": {}, "markets": []},
    )

    status = tracker.run_loop(
        interval_minutes=10.0,
        max_iterations=2,
        capture_fn=capture_fn,
        sleep_fn=sleep_fn,
        now_fn=clock.now,
    )

    assert len(seen_during_sleep) == 10  # 600 s idle in 60 s chunks
    for seen in seen_during_sleep:
        assert seen["consecutive_errors"] == 1
        assert seen["last_iteration_outcome"] == "error"
        assert seen["last_clean_iteration_at"] is None
        assert seen["iterations"] == 1
    # Read just before each beat: the heartbeat is exactly one cadence old.
    assert [
        _age_seconds(START + timedelta(seconds=60 * index), seen["last_heartbeat"])
        for index, seen in enumerate(seen_during_sleep, start=1)
    ] == [tracker.SLEEP_HEARTBEAT_SECONDS] * 10
    assert status["consecutive_errors"] == 0
    assert status["last_iteration_outcome"] == "clean"


def test_pause_flag_created_during_sleep_is_still_honoured_only_at_next_iteration(
    tmp_path,
    monkeypatch,
):
    clock = Clock()
    batches = _patch_loop(monkeypatch, tmp_path, clock)
    writes = _record_writes(monkeypatch)
    slept = []

    def sleep_fn(seconds):
        slept.append(seconds)
        clock.advance(seconds)
        if len(slept) == 1:
            (tmp_path / "pause.flag").write_text("", encoding="utf-8")

    status = tracker.run_loop(
        interval_minutes=10,
        max_iterations=2,
        sleep_fn=sleep_fn,
        now_fn=clock.now,
        available_memory_fn=lambda: 16 * GIB,
        trigger_queue_root=tmp_path / "trigger_queue",
    )

    # The sleep is neither shortened nor re-planned by the pause flag.
    assert sum(slept) == NEXT_DUE_SECONDS - BATCH_SECONDS
    # Idle heartbeats keep the recorded pause state; it flips only at iteration start.
    assert all(write["paused"] is False for write in writes if write["iterations"] == 1)
    assert status["paused"] is True
    assert len(batches) == 1


def test_stop_during_sleep_propagates_and_releases_the_writer_lock(tmp_path, monkeypatch):
    clock = Clock()
    _patch_loop(monkeypatch, tmp_path, clock)
    status_path = tmp_path / "loop_status.json"
    lock_path = status_path.with_name(f".{status_path.name}.writer.lock")

    def sleep_fn(seconds):
        clock.advance(seconds)
        if clock.now() - START >= timedelta(seconds=150):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        tracker.run_loop(
            interval_minutes=10,
            max_iterations=2,
            sleep_fn=sleep_fn,
            now_fn=clock.now,
            available_memory_fn=lambda: 16 * GIB,
            trigger_queue_root=tmp_path / "trigger_queue",
        )

    persisted = json.loads(status_path.read_text(encoding="utf-8"))
    assert persisted["iterations"] == 1
    assert persisted["last_iteration_outcome"] == "clean"
    assert not lock_path.exists()


def test_sleep_helper_beats_on_cadence_and_never_after_the_final_chunk(tmp_path):
    beats = []
    slept = []

    result = tracker.sleep_until_due_or_triggered_work(
        125,
        queue_root=tmp_path / "trigger_queue",
        sleep_fn=slept.append,
        check_seconds=5,
        heartbeat_fn=lambda: beats.append(sum(slept)),
        heartbeat_seconds=60,
    )

    assert result == {"interrupted": False, "remaining_seconds": 0.0}
    assert sum(slept) == 125
    assert beats == [60, 120]

    beats.clear()
    slept.clear()
    tracker.sleep_until_due_or_triggered_work(
        120,
        queue_root=tmp_path / "trigger_queue",
        sleep_fn=slept.append,
        check_seconds=5,
        heartbeat_fn=lambda: beats.append(sum(slept)),
        heartbeat_seconds=60,
    )
    assert beats == [60]


def test_triggered_work_interrupts_sleep_without_a_further_heartbeat(tmp_path):
    queue_root = tmp_path / "trigger_queue"
    beats = []
    slept = []

    def sleep_fn(seconds):
        slept.append(seconds)
        if sum(slept) == 65:
            enqueue_triggered_snapshot(
                market_id="toronto",
                target_date="2026-07-14",
                event_slug="event-toronto",
                trigger_context={
                    "current_observation": {"captured_at_utc": START.isoformat()},
                    "triggers": [{"reason": "wu_history_high_increased"}],
                },
                queue_root=queue_root,
                now=START,
            )

    result = tracker.sleep_until_due_or_triggered_work(
        288,
        queue_root=queue_root,
        sleep_fn=sleep_fn,
        check_seconds=5,
        heartbeat_fn=lambda: beats.append(sum(slept)),
        heartbeat_seconds=60,
    )

    assert result == {"interrupted": True, "remaining_seconds": 223.0}
    assert beats == [60]


def test_sleep_heartbeat_write_failure_does_not_kill_the_loop(tmp_path, monkeypatch):
    clock = Clock()
    batches = _patch_loop(monkeypatch, tmp_path, clock)
    original = tracker.write_loop_status
    phase = {"sleeping": False}

    def flaky_write(status):
        if phase["sleeping"]:
            raise PermissionError("synthetic replace race")
        return original(status)

    def sleep_fn(seconds):
        phase["sleeping"] = True
        clock.advance(seconds)

    def now_fn():
        if phase["sleeping"] and clock.now() - START >= timedelta(seconds=NEXT_DUE_SECONDS):
            phase["sleeping"] = False
        return clock.now()

    monkeypatch.setattr(tracker, "write_loop_status", flaky_write)
    status = tracker.run_loop(
        interval_minutes=10,
        max_iterations=2,
        sleep_fn=sleep_fn,
        now_fn=now_fn,
        available_memory_fn=lambda: 16 * GIB,
        trigger_queue_root=tmp_path / "trigger_queue",
    )

    assert status["iterations"] == 2
    assert len(batches) == 2


def _first_sleep_plan_and_beats(writes, marker):
    plan = writes[marker["index"]]
    beats = [write for write in writes[marker["index"] + 1:] if write["iterations"] == 1]
    return plan, beats


def _assert_liveness_only(plan, beats, expected_count):
    assert len(beats) == expected_count
    expected = {key: value for key, value in plan.items() if key != "last_heartbeat"}
    previous = datetime.fromisoformat(plan["last_heartbeat"])
    for write in beats:
        assert {key: value for key, value in write.items() if key != "last_heartbeat"} == expected
        beat = datetime.fromisoformat(write["last_heartbeat"])
        assert (beat - previous).total_seconds() == tracker.SLEEP_HEARTBEAT_SECONDS
        previous = beat


def test_sleep_helper_cadence_is_exact_when_the_check_interval_does_not_divide_it(tmp_path):
    beats = []
    slept = []

    result = tracker.sleep_until_due_or_triggered_work(
        288,
        queue_root=tmp_path / "trigger_queue",
        sleep_fn=slept.append,
        check_seconds=7,
        heartbeat_fn=lambda: beats.append(sum(slept)),
        heartbeat_seconds=60,
    )

    assert result == {"interrupted": False, "remaining_seconds": 0.0}
    # 7 s does not divide 60 s: the chunk before each boundary is shortened
    # (8 x 7 s + 4 s) instead of drifting the beats to 63/126/189/252 s.
    assert beats == [60, 120, 180, 240]
    assert sum(slept) == 288
    assert max(slept) <= 7
    assert slept[:9] == [7] * 8 + [4]

    beats.clear()
    slept.clear()
    tracker.sleep_until_due_or_triggered_work(
        200,
        queue_root=tmp_path / "trigger_queue",
        sleep_fn=slept.append,
        check_seconds=90,
        heartbeat_fn=lambda: beats.append(sum(slept)),
        heartbeat_seconds=60,
    )
    # A check interval longer than the cadence still beats exactly every 60 s.
    assert beats == [60, 120, 180]
    assert sum(slept) == 200


def _fail_idle_writes(monkeypatch):
    original_write = tracker.write_loop_status
    original_sleep = tracker.sleep_until_due_or_triggered_work
    phase = {"sleeping": False}

    def failing_idle_write(status):
        if phase["sleeping"]:
            raise PermissionError("synthetic disk refusal")
        return original_write(status)

    def tracked_sleep(*args, **kwargs):
        phase["sleeping"] = True
        try:
            return original_sleep(*args, **kwargs)
        finally:
            phase["sleeping"] = False

    monkeypatch.setattr(tracker, "write_loop_status", failing_idle_write)
    monkeypatch.setattr(tracker, "sleep_until_due_or_triggered_work", tracked_sleep)


def test_failed_sleep_heartbeat_writes_leave_one_rate_limited_diagnostic(tmp_path, monkeypatch):
    clock = Clock()
    batches = _patch_loop(monkeypatch, tmp_path, clock)
    _fail_idle_writes(monkeypatch)

    status = tracker.run_loop(
        interval_minutes=10,
        max_iterations=4,
        sleep_fn=clock.advance,
        now_fn=clock.now,
        available_memory_fn=lambda: 16 * GIB,
        trigger_queue_root=tmp_path / "trigger_queue",
    )

    assert status["iterations"] == 4
    assert len(batches) == 4
    records = [
        json.loads(line)
        for line in (tmp_path / "diagnostics.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    failures = [record for record in records if record.get("status") == "sleep_heartbeat_write_failed"]
    # Three 288 s sleeps fail 12 beats (72..252, 372..552, 672..852 s). The first
    # is recorded; the next record waits 600 s and counts the 7 in between.
    assert [
        (record["time"], record["suppressed_since_last_diagnostic"]) for record in failures
    ] == [
        ((START + timedelta(seconds=72)).isoformat(), 0),
        ((START + timedelta(seconds=672)).isoformat(), 7),
    ]
    assert failures[0]["error"] == "PermissionError: synthetic disk refusal"
    assert tracker.SLEEP_HEARTBEAT_FAILURE_DIAGNOSTIC_SECONDS == 600.0


def test_failed_heartbeat_diagnostic_write_is_also_swallowed(tmp_path, monkeypatch):
    clock = Clock()
    batches = _patch_loop(monkeypatch, tmp_path, clock)
    _fail_idle_writes(monkeypatch)
    original_append = tracker.append_diagnostic
    attempted = []

    def failing_append(record):
        if record.get("status") == "sleep_heartbeat_write_failed":
            attempted.append(record)
            raise OSError("synthetic diagnostics refusal")
        return original_append(record)

    monkeypatch.setattr(tracker, "append_diagnostic", failing_append)
    status = tracker.run_loop(
        interval_minutes=10,
        max_iterations=2,
        sleep_fn=clock.advance,
        now_fn=clock.now,
        available_memory_fn=lambda: 16 * GIB,
        trigger_queue_root=tmp_path / "trigger_queue",
    )

    assert status["iterations"] == 2
    assert len(batches) == 2
    assert len(attempted) == 1  # still rate-limited after a failed diagnostic


def test_sleep_after_a_paused_iteration_beats_and_keeps_the_pause_state(tmp_path, monkeypatch):
    clock = Clock()
    batches = _patch_loop(monkeypatch, tmp_path, clock)
    (tmp_path / "pause.flag").write_text("", encoding="utf-8")
    writes = _record_writes(monkeypatch)
    marker = {}

    def sleep_fn(seconds):
        marker.setdefault("index", len(writes) - 1)
        clock.advance(seconds)

    status = tracker.run_loop(
        interval_minutes=10,
        max_iterations=2,
        sleep_fn=sleep_fn,
        now_fn=clock.now,
        available_memory_fn=lambda: 16 * GIB,
        trigger_queue_root=tmp_path / "trigger_queue",
    )

    assert batches == []
    assert status["paused"] is True
    plan, beats = _first_sleep_plan_and_beats(writes, marker)
    assert plan["paused"] is True
    assert plan["last_sleep_seconds"] == 600.0
    assert plan["last_completed_iteration_at"] is None
    # A paused iteration plans the full 600 s interval: beats at 60..540 s.
    _assert_liveness_only(plan, beats, 9)


def test_sleep_after_a_debounced_stale_code_iteration_beats_without_progress(tmp_path, monkeypatch):
    clock = Clock()
    batches = _patch_loop(monkeypatch, tmp_path, clock)
    monkeypatch.setattr(
        tracker,
        "runtime_identity_status",
        lambda *_args, **_kwargs: {"runtime_code_state": "stale_code", "detail": "synthetic drift"},
    )
    monkeypatch.setattr(
        tracker,
        "readoption_debounce",
        lambda **_kwargs: {"debounced": True, "reason": "synthetic_recent_readoption"},
    )
    inline = []

    def inline_capture(force=False, market_id="toronto"):
        inline.append(clock.now())
        return {
            "written": True,
            "snapshot_id": f"{market_id}-inline-{len(inline)}",
            "next_due_at": (clock.now() + timedelta(seconds=NEXT_DUE_SECONDS)).isoformat(),
        }

    monkeypatch.setattr(tracker, "capture_snapshot", inline_capture)
    writes = _record_writes(monkeypatch)
    marker = {}

    def sleep_fn(seconds):
        marker.setdefault("index", len(writes) - 1)
        clock.advance(seconds)

    status = tracker.run_loop(
        interval_minutes=10,
        max_iterations=2,
        sleep_fn=sleep_fn,
        now_fn=clock.now,
        available_memory_fn=lambda: 16 * GIB,
        trigger_queue_root=tmp_path / "trigger_queue",
    )

    # Debounced re-adoption stays inline on the loaded code; it is not an exit.
    assert batches == []
    assert len(inline) == 2
    assert status["iterations"] == 2
    plan, beats = _first_sleep_plan_and_beats(writes, marker)
    assert plan["capture_execution"]["active_mode"] == "inline"
    assert plan["capture_execution"]["inline_reason"] == "runtime_re_adoption_debounce"
    assert plan["runtime_guard"]["readoption_debounce"]["debounced"] is True
    assert plan["last_sleep_seconds"] == float(NEXT_DUE_SECONDS)
    # 300 s idle: beats at 60/120/180/240 s, liveness only.
    _assert_liveness_only(plan, beats, 4)
