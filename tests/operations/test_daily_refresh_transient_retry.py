"""Post-step transient capture-degradation retry for Stage-A isolated steps.

Guards: the 2026-10-23 Stage-A incident (one transient ACTIVE_DEGRADED snapshot
cycle with a fresh heartbeat deferred the whole day after
public_wu_settlement_restore). The retry is bounded to 10 minutes and the
teardown deadline, and every non-transient blocker still defers immediately.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from weather.operations.daily_refresh_resources import (
    POST_STEP_TRANSIENT_RETRY_INTERVAL_SECONDS,
    POST_STEP_TRANSIENT_RETRY_MAX_SECONDS,
    await_transient_capture_recovery,
    stage_teardown_deadline_utc,
    transient_capture_degradation_only,
)

START = datetime(2026, 10, 23, 14, 35, tzinfo=timezone.utc)
FAR_DEADLINE = START + timedelta(hours=2)


class FakeClock:
    def __init__(self, start=START):
        self.now = start
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now = self.now + timedelta(seconds=seconds)


def _loop(name="snapshot", *, active=True, fresh=True, reasons=("consecutive_errors", "last_error_present")):
    reasons = sorted(reasons)
    return {
        "name": name,
        "active": active,
        "heartbeat_fresh": fresh,
        "degraded": bool(reasons) or not fresh,
        "degraded_reasons": reasons,
        "state": "ACTIVE_DEGRADED" if active else "INACTIVE_DEGRADED",
        "heartbeat_age_seconds": 19.0 if fresh else 900.0,
    }


def _blocked(*loops, extra_blockers=()):
    blockers = [
        {
            "code": "capture_loop_not_fresh",
            "loop": loop["name"],
            "state": loop["state"],
            "degraded_reasons": loop["degraded_reasons"],
            "heartbeat_age_seconds": loop["heartbeat_age_seconds"],
        }
        for loop in loops
    ]
    blockers.extend(extra_blockers)
    return {"status": "BLOCK", "decision": "DEFER", "capture_loops": list(loops), "blockers": blockers}


ADMIT = {"status": "PASS", "decision": "ADMIT", "capture_loops": [_loop(reasons=())], "blockers": []}
MEMORY_BLOCKER = {"code": "insufficient_physical_availability", "available_bytes": 1, "required_available_bytes": 2}


def _args(clock, *, deadline=FAR_DEADLINE, stage="settlement"):
    logs = []
    args = SimpleNamespace(
        stage=stage,
        _stage_a_now_fn=clock,
        _stage_a_sleep_fn=clock.sleep,
        _stage_a_retry_log_fn=logs.append,
        _stage_a_teardown_deadline_utc=deadline,
    )
    return args, logs


def _sequence(*admissions):
    calls = []
    remaining = list(admissions)

    def admission_fn(args, step_name, budget, *, phase):
        calls.append(phase)
        return remaining.pop(0)

    return admission_fn, calls


def test_clean_on_second_check_continues():
    clock = FakeClock()
    args, logs = _args(clock)
    admission_fn, calls = _sequence(_blocked(_loop()), ADMIT)
    final, record = await_transient_capture_recovery(
        args, "public_wu_settlement_restore", {}, _blocked(_loop()), admission_fn=admission_fn
    )
    assert final["decision"] == "ADMIT"
    assert record["outcome"] == "recovered"
    assert record["recheck_count"] == 2
    assert calls == ["after", "after"]
    assert clock.sleeps == [POST_STEP_TRANSIENT_RETRY_INTERVAL_SECONDS] * 2
    assert record["waited_seconds"] == 2 * POST_STEP_TRANSIENT_RETRY_INTERVAL_SECONDS
    assert [sample["decision"] for sample in record["rechecks"]] == ["DEFER", "ADMIT"]
    # one start line, one line per re-check, one outcome line
    assert len(logs) == 4


def test_stays_degraded_defers_after_ten_minutes():
    clock = FakeClock()
    args, _logs = _args(clock)
    expected_checks = int(POST_STEP_TRANSIENT_RETRY_MAX_SECONDS // POST_STEP_TRANSIENT_RETRY_INTERVAL_SECONDS)
    admission_fn, calls = _sequence(*[_blocked(_loop()) for _ in range(expected_checks + 5)])
    final, record = await_transient_capture_recovery(
        args, "step", {}, _blocked(_loop()), admission_fn=admission_fn
    )
    assert final["decision"] == "DEFER"
    assert record["outcome"] == "still_degraded"
    assert len(calls) == expected_checks
    assert sum(clock.sleeps) == POST_STEP_TRANSIENT_RETRY_MAX_SECONDS
    assert record["bounded_by_deadline"] is False


def test_mixed_blockers_defer_immediately():
    clock = FakeClock()
    args, logs = _args(clock)
    admission_fn, calls = _sequence(ADMIT)
    initial = _blocked(
        _loop(),
        extra_blockers=[{"code": "required_capture_loop_inactive", "loop": "observation", "state": "INACTIVE"}],
    )
    final, record = await_transient_capture_recovery(args, "step", {}, initial, admission_fn=admission_fn)
    assert record is None and final is initial
    assert calls == [] and clock.sleeps == [] and logs == []
    # a second loop with an extra degraded reason is also not transient
    other = _blocked(_loop(), _loop("microstructure", reasons=("consecutive_errors", "writer_lock_missing")))
    assert transient_capture_degradation_only(other) is False


def test_stale_heartbeat_defers_immediately():
    clock = FakeClock()
    args, _logs = _args(clock)
    admission_fn, calls = _sequence(ADMIT)
    for initial in (
        _blocked(_loop(fresh=False, reasons=("consecutive_errors",))),
        _blocked(_loop(fresh=False, reasons=("consecutive_errors", "heartbeat_stale"))),
        _blocked(_loop(active=False)),
        _blocked(_loop(reasons=())),
    ):
        final, record = await_transient_capture_recovery(args, "step", {}, initial, admission_fn=admission_fn)
        assert record is None and final is initial
    assert calls == [] and clock.sleeps == []


def test_deadline_shorter_than_ten_minutes_bounds_the_wait():
    clock = FakeClock()
    args, _logs = _args(clock, deadline=START + timedelta(seconds=95))
    admission_fn, calls = _sequence(*[_blocked(_loop()) for _ in range(20)])
    final, record = await_transient_capture_recovery(
        args, "step", {}, _blocked(_loop()), admission_fn=admission_fn
    )
    assert final["decision"] == "DEFER"
    assert record["outcome"] == "deadline_exhausted"
    assert record["bounded_by_deadline"] is True
    assert record["wait_budget_seconds"] == 95
    assert len(calls) == 3
    assert clock.now <= START + timedelta(seconds=95)
    # a deadline already reached means no wait at all
    clock2 = FakeClock()
    args2, _ = _args(clock2, deadline=START - timedelta(seconds=1))
    admission_fn2, calls2 = _sequence(ADMIT)
    final2, record2 = await_transient_capture_recovery(
        args2, "step", {}, _blocked(_loop()), admission_fn=admission_fn2
    )
    assert final2["decision"] == "DEFER" and record2["recheck_count"] == 0
    assert calls2 == [] and clock2.sleeps == []


def test_memory_blocker_defers_immediately_and_stops_a_running_wait():
    clock = FakeClock()
    args, _logs = _args(clock)
    admission_fn, calls = _sequence(ADMIT)
    initial = _blocked(_loop(), extra_blockers=[MEMORY_BLOCKER])
    final, record = await_transient_capture_recovery(args, "step", {}, initial, admission_fn=admission_fn)
    assert record is None and final is initial and calls == []
    memory_only = {"status": "BLOCK", "decision": "DEFER", "capture_loops": [], "blockers": [MEMORY_BLOCKER]}
    assert transient_capture_degradation_only(memory_only) is False
    # a memory blocker appearing mid-wait ends the wait at once
    admission_fn, calls = _sequence(_blocked(_loop(), extra_blockers=[MEMORY_BLOCKER]), ADMIT)
    final, record = await_transient_capture_recovery(
        args, "step", {}, _blocked(_loop()), admission_fn=admission_fn
    )
    assert record["outcome"] == "non_transient_blocker"
    assert final["decision"] == "DEFER" and len(calls) == 1


def test_default_deadline_mirrors_wrapper_teardown():
    args = SimpleNamespace(stage="settlement")
    local_tz = datetime.now().astimezone().tzinfo
    at_ten = datetime(2026, 10, 23, 10, 0, tzinfo=local_tz)
    deadline = stage_teardown_deadline_utc(args, at_ten.astimezone(timezone.utc))
    assert deadline.astimezone(local_tz).replace(tzinfo=None) == datetime(2026, 10, 23, 11, 55)
    after = datetime(2026, 10, 23, 11, 56, tzinfo=local_tz).astimezone(timezone.utc)
    assert stage_teardown_deadline_utc(args, after) == after
    before_open = datetime(2026, 10, 23, 0, 10, tzinfo=local_tz).astimezone(timezone.utc)
    assert stage_teardown_deadline_utc(args, before_open) == before_open
    evidence = SimpleNamespace(stage="evidence")
    early = datetime(2026, 10, 23, 8, 0, tzinfo=local_tz)
    assert stage_teardown_deadline_utc(evidence, early.astimezone(timezone.utc)).astimezone(
        local_tz
    ).replace(tzinfo=None) == datetime(2026, 10, 23, 9, 0)
