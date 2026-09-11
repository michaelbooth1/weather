"""Archive policy boundaries and coherent native system-memory measurements."""
import os

import pytest

from weather.operations import cold_archive_resource_policy as policy
from weather.operations import production_cold_archive_stage_cli as archive
from weather.operations import replay_cache_compression_admission as shared
from tests.operations.test_production_cold_archive_stage_cli import resources


@pytest.mark.parametrize("commit,archive_ok,ordinary_ok", [
    (69.9, True, True), (70, True, False), (79.9, True, False),
    (80, False, False), (80.1, False, False), (None, False, False),
    (float("nan"), False, False), (float("inf"), False, False), (True, False, False),
])
def test_only_archive_has_the_new_commit_limit(commit, archive_ok, ordinary_ok):
    values = resources()
    values["commit"] = commit
    result = archive.check_resources(**values)
    assert (result["status"] == "PASS") is archive_ok
    assert result["maximum_host_commit_percent"] == 80
    ordinary = shared.check_capture_health(
        **{key: values[key] for key in ("now", "available", "commit", "loops")})
    assert (ordinary["status"] == "PASS") is ordinary_ok
    assert ordinary["maximum_host_commit_percent"] == 70
    if commit == 80:
        assert "commit_not_below_80_percent" in result["reasons"]


@pytest.mark.parametrize("change", [
    {"available": policy.MIN_AVAILABLE_BYTES - 1}, {"available": None}, {"loops": []},
])
def test_more_commit_headroom_never_bypasses_other_guards(change):
    values = {**resources(), "commit": 75, **change}
    assert archive.check_resources(**values)["status"] == "BLOCK"


def test_start_margin_requires_consecutive_good_observations():
    gate = policy.AdmissionStartWindow()
    good = {"status": "PASS", "host_commit_percent": 77.9,
            "available_memory_bytes": policy.MIN_AVAILABLE_BYTES}
    assert [gate.observe(good) for _ in range(4)] == [False] * 4
    assert not gate.observe({**good, "host_commit_percent": 78})
    assert [gate.observe(good) for _ in range(4)] == [False] * 4
    assert gate.observe(good)
    assert not gate.observe({**good, "status": "BLOCK"})
    assert not gate.observe({**good, "available_memory_bytes": None})


def test_system_measurement_uses_pages_and_coherent_physical_values():
    result = policy.measurement_from_pages(
        committed=750, limit=1000, physical=512, available=256, page_size=4096)
    assert result == {
        "api": "GetPerformanceInfo", "commit_total_bytes": 750 * 4096,
        "commit_limit_bytes": 1000 * 4096, "physical_total_bytes": 512 * 4096,
        "available_memory_bytes": 256 * 4096, "host_commit_percent": 75.0,
    }


@pytest.mark.parametrize("changed", [
    {"limit": 0}, {"committed": 1001}, {"available": 513},
    {"page_size": 0}, {"physical": -1}, {"committed": True},
])
def test_invalid_native_measurement_fails_closed(changed):
    values = {"committed": 750, "limit": 1000, "physical": 512,
              "available": 256, "page_size": 4096}
    assert policy.measurement_from_pages(**{**values, **changed}) is None


@pytest.mark.skipif(os.name != "nt", reason="native Windows memory API")
def test_native_system_memory_reader():
    result = policy.read_host_memory()
    assert result is not None
    assert result["api"] == "GetPerformanceInfo"
    assert 0 <= result["host_commit_percent"] <= 100
    assert 0 <= result["available_memory_bytes"] <= result["physical_total_bytes"]
    assert result["commit_limit_bytes"] >= result["commit_total_bytes"]


@pytest.mark.skipif(os.name != "nt", reason="native Windows nested Job")
def test_native_system_commit_is_independent_of_process_memory_limit():
    import ctypes
    from ctypes import wintypes
    import json
    from pathlib import Path
    import subprocess
    import sys

    class Basic(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
            ("flags", wintypes.DWORD), ("minimum", ctypes.c_size_t),
            ("maximum", ctypes.c_size_t), ("active", wintypes.DWORD),
            ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]
    class Extended(ctypes.Structure):
        _fields_ = [("basic", Basic), ("io", IO)] + [
            (name, ctypes.c_size_t) for name in ("process", "job", "peak_process", "peak_job")]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    limits = Extended()
    limits.basic.flags = 0x100 | 0x2000  # Per-process memory and kill on Job close.
    limits.process = 128 * 1024**2
    job = kernel.CreateJobObjectW(None, None)
    assert job
    child = None
    try:
        assert kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
        before = policy.read_host_memory()
        code = ("import sys,json; sys.stdin.readline(); "
                "from weather.operations.cold_archive_resource_policy import read_host_memory; "
                "print(json.dumps(read_host_memory()))")
        child = subprocess.Popen(
            [sys.executable, "-c", code], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=Path(policy.__file__).resolve().parents[3],
            creationflags=subprocess.CREATE_NO_WINDOW)
        assert kernel.AssignProcessToJobObject(job, int(child._handle))
        stdout, stderr = child.communicate("go\n", timeout=15)
        assert child.returncode == 0, stderr
        inside = json.loads(stdout)
        after = policy.read_host_memory()
        assert inside["api"] == "GetPerformanceInfo"
        assert inside["commit_limit_bytes"] > 10 * limits.process
        assert min(before["commit_limit_bytes"], after["commit_limit_bytes"]) <= (
            inside["commit_limit_bytes"]) <= max(
                before["commit_limit_bytes"], after["commit_limit_bytes"])
        assert inside["physical_total_bytes"] == before["physical_total_bytes"]
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        kernel.CloseHandle(job)


def idle_snapshot_resources():
    values = resources()
    values["loops"][0].update(heartbeat_age_seconds=300.02,
        last_clean_iteration_age_seconds=300, last_sleep_seconds=400, markets_in_progress=[])
    return values


def test_only_archive_accepts_verified_planned_snapshot_sleep():
    values = idle_snapshot_resources()
    assert archive.check_resources(**values)["status"] == "PASS"
    ordinary = shared.check_capture_health(
        **{key: values[key] for key in ("now", "available", "commit", "loops")})
    assert ordinary["status"] == "BLOCK"
    assert "capture_unhealthy:snapshot" in ordinary["reasons"]


@pytest.mark.parametrize("change", [
    {"heartbeat_age_seconds": 410.01, "last_clean_iteration_age_seconds": 410},
    {"heartbeat_age_seconds": 299},  # New iteration heartbeat follows last clean completion.
    {"heartbeat_age_seconds": 302},  # No matching completed iteration.
    {"last_clean_iteration_age_seconds": None}, {"last_sleep_seconds": None},
    {"last_sleep_seconds": 600.1}, {"last_sleep_seconds": 180},
    {"last_sleep_seconds": True}, {"last_sleep_seconds": float("nan")},
    {"last_sleep_seconds": float("inf")}, {"markets_in_progress": None},
    {"markets_in_progress": ["denver"]}, {"active": False}, {"degraded": True},
    {"heartbeat_fresh": False}, {"pid_agreement": False},
    {"process_identity_matches_lock": False},
    {"process_diagnostics": {"status_pid_alive": False, "lock_pid_alive": True}},
])
def test_planned_sleep_never_masks_busy_stale_or_unhealthy_capture(change):
    values = idle_snapshot_resources()
    values["loops"][0].update(change)
    assert archive.check_resources(**values)["status"] == "BLOCK"


def test_planned_sleep_is_bounded_and_never_applies_to_other_producers():
    values = idle_snapshot_resources()
    values["loops"][0].update(heartbeat_age_seconds=610,
        last_clean_iteration_age_seconds=609.99, last_sleep_seconds=600)
    assert archive.check_resources(**values)["status"] == "PASS"
    values["loops"][0]["heartbeat_age_seconds"] = 610.01
    assert archive.check_resources(**values)["status"] == "BLOCK"
    values = idle_snapshot_resources()
    values["loops"][1].update(heartbeat_age_seconds=300.02,
        last_clean_iteration_age_seconds=300, last_sleep_seconds=400, markets_in_progress=[])
    assert archive.check_resources(**values)["status"] == "BLOCK"
