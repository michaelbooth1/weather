"""Current, handle-bound proofs for exact WU atomic temporary files."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from dataclasses import asdict
import math
import os
from pathlib import Path, PurePosixPath
import re
import time

from weather.operations.cold_archive_native_removal import ExactNtfsRemoval
from weather.operations.production_cold_archive_stage import _ArchiveSource, _safe_path
from weather.operations.storage_classes import WuAtomicOrphanProof, classification_payload

TEMP_NAME = re.compile(r"(.+)\.([1-9][0-9]*)\.([0-9]+)\.tmp")


class OrphanRefused(ValueError):
    """A named missing proof, never authority to weaken a check."""


class Budget:
    def __init__(self, max_bytes, max_seconds, *, clock=time.monotonic):
        if (type(max_bytes) is not int or not 0 < max_bytes <= 1024**3
                or not math.isfinite(max_seconds) or not 0 < max_seconds <= 1800):
            raise OrphanRefused("invalid_budget")
        self.max_bytes, self.bytes_read = max_bytes, 0
        self.clock, self.deadline = clock, clock() + max_seconds

    def admit(self):
        if self.clock() >= self.deadline:
            raise OrphanRefused("time_cap")

    def reserve(self, size):
        self.admit()
        if size < 0 or self.bytes_read + size > self.max_bytes:
            raise OrphanRefused("byte_cap")

    def account(self, size):
        self.bytes_read += size
        if self.bytes_read > self.max_bytes:
            raise OrphanRefused("byte_cap")
        self.admit()


def writer_identity(pid):
    """Query one Windows process handle; access denial is unknown, never dead."""
    if os.name != "nt":
        raise OrphanRefused("native_windows_required")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "GetProcessTimes": ([wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)], wintypes.BOOL),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(kernel, name)
        fn.argtypes, fn.restype = args, result
    if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF:
        raise OrphanRefused("writer_identity_unknown")
    handle = kernel.OpenProcess(0x1000 | 0x00100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # ERROR_INVALID_PARAMETER: PID absent.
            return False, None
        raise OrphanRefused("writer_identity_unknown")
    try:
        state = kernel.WaitForSingleObject(handle, 0)
        if state == 0:
            return False, None
        if state != 258:
            raise OrphanRefused("writer_identity_unknown")
        stamps = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in stamps)):
            raise OrphanRefused("writer_identity_unknown")
        started = ((stamps[0].dwHighDateTime << 32) | stamps[0].dwLowDateTime) / 10_000_000 - 11644473600
        return True, started
    finally:
        kernel.CloseHandle(handle)


def candidate_path(root, relative):
    if not isinstance(relative, str) or "\\" in relative or ":" in relative:
        raise OrphanRefused("invalid_wu_path")
    path = PurePosixPath(relative)
    if (path.is_absolute() or path.as_posix() != relative or len(path.parts) < 3
            or path.parts[0] != "wunderground"
            or any(p in {".", ".."} or p.endswith((" ", ".")) for p in path.parts)):
        raise OrphanRefused("invalid_wu_path")
    match = TEMP_NAME.fullmatch(path.name)
    if not match or match[1].endswith(".tmp"):
        raise OrphanRefused("invalid_atomic_temp_name")
    target = Path(root).absolute() / relative
    _safe_path(target)
    sibling = target.with_name(match[1])
    return target, sibling, int(match[2])


def current_proof(relative, metadata, pid, *, process_reader=writer_identity, now=time.time):
    alive, started = process_reader(pid)
    proof = WuAtomicOrphanProof(relative, pid, alive, started,
        metadata["mtime_ns"] / 1_000_000_000, now(), True, True)
    if classification_payload(relative, wu_orphan_proof=proof)["artifact_family"] != "wu_atomic_write_orphan":
        if proof.checked_at - proof.mtime <= 86400:
            raise OrphanRefused("age_not_over_24_hours")
        raise OrphanRefused("writer_not_proved_released")
    return proof


@contextmanager
def observe(root, relative, *, budget, process_reader=writer_identity, now=time.time,
            pin_factory=ExactNtfsRemoval, final_factory=_ArchiveSource):
    """Keep the temp exclusive and final read-pinned until the caller finishes."""
    budget.admit()
    target, final, pid = candidate_path(root, relative)
    try:
        _safe_path(final)
    except (OSError, ValueError):
        raise OrphanRefused("final_sibling_unavailable") from None
    with pin_factory(target) as pin, final_factory(final) as final_pin:
        metadata, final_metadata = pin.metadata(), final_pin.metadata()
        budget.reserve(metadata["size_bytes"])
        proof = current_proof(relative, metadata, pid, process_reader=process_reader, now=now)
        sha = pin.digest(guard=budget)
        proof = current_proof(relative, metadata, pid, process_reader=process_reader, now=now)
        row = dict(path=relative, data_path=relative, bytes=metadata["size_bytes"], sha256=sha,
            metadata=metadata, final_path=final.relative_to(Path(root).absolute()).as_posix(),
            final_metadata=final_metadata, wu_orphan_proof=asdict(proof),
            deletion_reason="proved abandoned WU atomic temporary file",
            **classification_payload(relative, wu_orphan_proof=proof))
        yield pin, final_pin, row, proof


def compare_record(expected, current):
    for key in ("path", "data_path", "bytes", "sha256", "metadata", "final_path", "final_metadata",
                "storage_class", "artifact_family"):
        if expected.get(key) != current.get(key):
            raise OrphanRefused("manifest_binding_changed:" + key)
    try:
        planned = WuAtomicOrphanProof(**expected["wu_orphan_proof"])
        if classification_payload(expected["path"], wu_orphan_proof=planned)["artifact_family"] != "wu_atomic_write_orphan":
            raise ValueError
        if planned.mtime != current["wu_orphan_proof"]["mtime"] or planned.writer_pid != current["wu_orphan_proof"]["writer_pid"]:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise OrphanRefused("invalid_planned_proof") from None


def verify_record(candidate, root):
    """Fresh standalone cleanup preflight; stored booleans are not authority."""
    with observe(root, candidate["path"], budget=Budget(1024**3, 30)) as (_, _, row, proof):
        compare_record(candidate, row)
        return proof
