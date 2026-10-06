"""The nightly must survive a capture loop atomically replacing its live status file.

2026-10-03: the nightly failed after 87 batches with PermissionError on
data/snapshots/clob_loop_status.json, read by the per-second capture admission.
"""
from contextlib import contextmanager
from datetime import date
import os

import pytest

from weather.operations import cold_snapshot_nightly as night
from weather.operations import storage_recovery_inventory as inventory
from weather.operations.replay_cache_compression_admission import _bounded_status

AS_OF = date(2026, 10, 3)
CLOSED = ("highest-temperature-in-nyc-on-september-30-2026", "highest-temperature-in-austin-on-september-29-2026")
HOT = "highest-temperature-in-nyc-on-october-2-2026"
windows = pytest.mark.skipif(os.name != "nt", reason="native NTFS sharing semantics")


@contextmanager
def held(path, mode):
    """Hold ``path`` delete-pending (a replace in flight) or exclusively open."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # DELETE | GENERIC_READ; full sharing for delete-pending, none for exclusive.
    handle = kernel.CreateFileW(str(path), 0x00010000 | 0x80000000,
                                7 if mode == "delete_pending" else 0, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if mode == "delete_pending":
            flag = ctypes.c_ubyte(1)  # FILE_DISPOSITION_INFO, legacy (non-POSIX) semantics.
            if not kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(flag), 1):
                raise ctypes.WinError(ctypes.get_last_error())
        yield
    finally:
        kernel.CloseHandle(handle)


def snapshot_root(tmp_path):
    snapshots = tmp_path / "data" / "snapshots"
    for name in (*CLOSED, HOT):
        (snapshots / name).mkdir(parents=True)
    for name in ("clob_loop_status.json", ".clob_loop_status.json.writer.lock", "loop_status.json"):
        (snapshots / name).write_text("{}")
    return snapshots


@windows
@pytest.mark.parametrize("mode", ["delete_pending", "exclusive"])
def test_selection_never_touches_a_held_root_status_file(tmp_path, monkeypatch, mode):
    snapshots = snapshot_root(tmp_path)
    status = snapshots / "clob_loop_status.json"
    checked = []
    original = inventory.checked_stat

    def recording(path, *, directory):
        checked.append(path)
        return original(path, directory=directory)

    monkeypatch.setattr(inventory, "checked_stat", recording)
    with held(status, mode), held(snapshots / ".clob_loop_status.json.writer.lock", mode):
        with pytest.raises(PermissionError):
            status.open("rb")  # The fixture really reproduces the production error.
        selected = night.closed_folders(tmp_path / "data", AS_OF, lambda: None)
    assert selected == ["snapshots/" + CLOSED[1], "snapshots/" + CLOSED[0]]
    # Only the root's ancestors and the selected closed-day folders are stat'ed.
    assert [p.name for p in checked if p.parent == snapshots] == [CLOSED[0], CLOSED[1]] or \
        sorted(p.name for p in checked if p.parent == snapshots) == sorted(CLOSED)


@windows
def test_selection_refuses_an_error_inside_a_selected_closed_folder(tmp_path, monkeypatch):
    snapshot_root(tmp_path)
    original = inventory.checked_stat

    def denied(path, *, directory):
        if path.name == CLOSED[0]:
            raise PermissionError(13, "Permission denied", str(path))
        return original(path, directory=directory)

    monkeypatch.setattr(inventory, "checked_stat", denied)
    with pytest.raises(PermissionError):
        night.closed_folders(tmp_path / "data", AS_OF, lambda: None)


def notes():
    return {"admission_retries": 0, "admission_retry_notes": []}


PASS = {"status": "PASS", "reasons": []}
BLOCK = {"status": "BLOCK", "reasons": ["capture_unhealthy:clob"]}


def sequence(*outcomes):
    calls = []

    def observe(root, resources):
        calls.append(root)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome
    return observe, calls


def test_admission_pass_needs_no_retry():
    observe, calls = sequence(PASS)
    record, slept = notes(), []
    assert night.observe_admission("root", None, record, observe=observe, sleep=slept.append) is PASS
    assert (len(calls), slept, record) == (1, [], notes())


@pytest.mark.parametrize("first", [PermissionError(13, "Permission denied", "clob_loop_status.json"), BLOCK])
def test_transient_status_race_is_reobserved_once_and_noted(first):
    observe, calls = sequence(first, PASS)
    record, slept = notes(), []
    assert night.observe_admission("root", None, record, observe=observe, sleep=slept.append) is PASS
    assert len(calls) == 2 and slept == [night.ADMISSION_RETRY_SECONDS]
    assert record["admission_retries"] == 1
    observation = record["admission_retry_notes"][0]["first_observation"]
    assert observation.startswith("PermissionError" if isinstance(first, OSError) else "BLOCK: capture_unhealthy:clob")


def test_persistent_permission_error_still_refuses():
    error = PermissionError(13, "Permission denied", "clob_loop_status.json")
    observe, _ = sequence(error, error)
    with pytest.raises(PermissionError):
        night.observe_admission("root", None, notes(), observe=observe, sleep=lambda _: None)


def test_persistent_block_is_returned_for_the_guard_to_refuse():
    observe, _ = sequence(BLOCK, BLOCK)
    assert night.observe_admission("root", None, notes(), observe=observe, sleep=lambda _: None) is BLOCK


def test_other_errors_are_not_retried():
    observe, calls = sequence(ValueError("capture status/lock exceeds its admission read bound"), PASS)
    with pytest.raises(ValueError):
        night.observe_admission("root", None, notes(), observe=observe, sleep=lambda _: None)
    assert len(calls) == 1


def test_retry_notes_are_bounded_but_counted():
    record = notes()
    for _ in range(night.MAX_ADMISSION_NOTES + 5):
        observe, _ = sequence(BLOCK, PASS)
        night.observe_admission("root", None, record, observe=observe, sleep=lambda _: None)
    assert record["admission_retries"] == night.MAX_ADMISSION_NOTES + 5
    assert len(record["admission_retry_notes"]) == night.MAX_ADMISSION_NOTES


@windows
def test_real_delete_pending_status_read_recovers_after_the_replace(tmp_path):
    status = tmp_path / "clob_loop_status.json"
    status.write_text('{"pid": 1}')
    holder = held(status, "delete_pending")
    holder.__enter__()
    released = []

    def observe(root, resources):
        _bounded_status(status, 1024 * 1024)  # The exact unguarded admission read.
        return PASS

    def replace_completes(_):
        holder.__exit__(None, None, None)  # Old file goes; the producer's new one lands.
        released.append(True)
        status.write_text('{"pid": 2}')

    record = notes()
    try:
        assert night.observe_admission(tmp_path, None, record, observe=observe, sleep=replace_completes) is PASS
    finally:
        if not released:
            holder.__exit__(None, None, None)
    assert record["admission_retries"] == 1
    assert "Permission denied" in record["admission_retry_notes"][0]["first_observation"]
