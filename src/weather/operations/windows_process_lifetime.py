"""Fail-closed Windows process-tree lifetime peak accounting."""

from __future__ import annotations

import os
import time


DEFAULT_MAX_TRACKED_PROCESSES = 1024
DEFAULT_MAX_CAPTURE_FAILURES = 1024


def summarize_process_lifetime(
    records,
    capture_failures,
    accounting,
    *,
    retained_handle_count,
    closed_handle_count,
    max_processes=DEFAULT_MAX_TRACKED_PROCESSES,
):
    rows = sorted(
        (dict(row) for row in records),
        key=lambda row: (
            int(row.get("creation_time_100ns") or 0),
            int(row.get("pid") or 0),
        ),
    )
    failures = [dict(row) for row in capture_failures]
    total_processes = int((accounting or {}).get("total_processes") or 0)
    active_processes = int((accounting or {}).get("active_processes") or 0)
    terminated_processes = int(
        (accounting or {}).get("terminated_processes") or 0
    )
    identities = [
        (
            int(row.get("pid") or 0),
            int(row.get("creation_time_100ns") or 0),
        )
        for row in rows
    ]
    working_set_upper_bound = sum(
        int(row.get("peak_working_set_bytes") or 0) for row in rows
    )
    commit_upper_bound = sum(
        int(row.get("peak_commit_bytes") or 0) for row in rows
    )
    checks = {
        "job_quiesced": active_processes == 0,
        "no_job_limit_terminated_processes": terminated_processes == 0,
        "tracker_cardinality_bounded": (
            0 < total_processes <= int(max_processes)
            and 0 < len(rows) <= int(max_processes)
        ),
        "every_job_process_observed": len(rows) == total_processes,
        "unique_process_instances": len(set(identities)) == len(identities),
        "no_capture_failures": not failures,
        "capture_failure_cardinality_bounded": (
            len(failures) <= int(max_processes)
        ),
        "all_processes_job_bound": all(
            row.get("job_membership_verified") is True
            and int(row.get("job_membership_observations") or 0) > 0
            for row in rows
        ),
        "all_process_images_identified": all(
            bool(row.get("image_path")) for row in rows
        ),
        "all_processes_signaled_exit": all(
            row.get("process_exited") is True for row in rows
        ),
        "all_terminal_queries_succeeded": all(
            row.get("terminal_query_succeeded") is True for row in rows
        ),
        "all_process_identities_stable": all(
            row.get("creation_time_identity_match") is True for row in rows
        ),
        "all_exit_times_present": all(
            int(row.get("exit_time_100ns") or 0) > 0 for row in rows
        ),
        "all_lifetime_peaks_positive": all(
            int(row.get("peak_working_set_bytes") or 0) > 0
            and int(row.get("peak_commit_bytes") or 0) > 0
            for row in rows
        ),
        "all_retained_handles_closed": (
            int(retained_handle_count) == len(rows)
            and int(closed_handle_count) == int(retained_handle_count)
        ),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "max_tracked_processes": int(max_processes),
        "job_total_processes": total_processes,
        "job_active_processes": active_processes,
        "job_terminated_processes": terminated_processes,
        "tracked_process_count": len(rows),
        "retained_handle_count": int(retained_handle_count),
        "closed_handle_count": int(closed_handle_count),
        "lifetime_working_set_upper_bound_bytes": working_set_upper_bound,
        "lifetime_commit_upper_bound_bytes": commit_upper_bound,
        "capture_failures": failures,
        "processes": rows,
        "checks": checks,
    }


class WindowsProcessLifetimeTracker:
    """Retain one handle per Job process and query final PSAPI peaks on exit."""

    def __init__(self, *, max_processes=DEFAULT_MAX_TRACKED_PROCESSES):
        if os.name != "nt":
            raise RuntimeError("Windows process lifetime tracking is Windows-only")
        if int(max_processes) <= 0:
            raise ValueError("max_processes must be positive")

        import ctypes
        import threading
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._threading = threading
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self._max_processes = int(max_processes)
        self._records = {}
        self._failures = {}
        self._capture_calls = 0
        self._late_duplicate_notification_count = 0
        self._closed = False
        self._failure_overflow_count = 0
        self._closed_handle_count = 0
        self._lock = threading.RLock()
        self._job = None
        self._job_handle = None
        self._completion_key = 0xC0D3
        self._sentinel_key = 0xC0D4
        self._completion_port = None
        self._completion_watcher = None
        self._completion_port_associated = False
        self._job_inactive_at_association = False
        self._completion_thread_started = False
        self._completion_queue_flushed = False
        self._completion_message_counts = {}
        self._barrier_seen = threading.Event()
        self._stop_requested = threading.Event()
        self._watcher_ready = threading.Event()

        class FILETIME(ctypes.Structure):
            _fields_ = [
                ("dwLowDateTime", wintypes.DWORD),
                ("dwHighDateTime", wintypes.DWORD),
            ]

        class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        class JOBOBJECT_ASSOCIATE_COMPLETION_PORT(ctypes.Structure):
            _fields_ = [
                ("CompletionKey", ctypes.c_void_p),
                ("CompletionPort", wintypes.HANDLE),
            ]

        self._filetime_type = FILETIME
        self._memory_counters_type = PROCESS_MEMORY_COUNTERS_EX
        self._completion_port_info_type = (
            JOBOBJECT_ASSOCIATE_COMPLETION_PORT
        )
        kernel32 = self._kernel32
        kernel32.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.GetProcessTimes.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(FILETIME),
            ctypes.POINTER(FILETIME),
            ctypes.POINTER(FILETIME),
            ctypes.POINTER(FILETIME),
        )
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.QueryFullProcessImageNameW.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        )
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
        )
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CreateIoCompletionPort.argtypes = (
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.c_size_t,
            wintypes.DWORD,
        )
        kernel32.CreateIoCompletionPort.restype = wintypes.HANDLE
        kernel32.GetQueuedCompletionStatus.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_void_p),
            wintypes.DWORD,
        )
        kernel32.GetQueuedCompletionStatus.restype = wintypes.BOOL
        kernel32.PostQueuedCompletionStatus.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.c_size_t,
            ctypes.c_void_p,
        )
        kernel32.PostQueuedCompletionStatus.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.IsProcessInJob.argtypes = (
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.BOOL),
        )
        kernel32.IsProcessInJob.restype = wintypes.BOOL
        self._psapi.GetProcessMemoryInfo.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
            wintypes.DWORD,
        )
        self._psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        self._completion_port = kernel32.CreateIoCompletionPort(
            ctypes.c_void_p(-1),
            None,
            0,
            1,
        )
        if not self._completion_port:
            error = ctypes.get_last_error()
            raise OSError(error, ctypes.FormatError(error))

    @staticmethod
    def _filetime_value(value):
        return (
            int(value.dwHighDateTime) << 32
        ) | int(value.dwLowDateTime)

    def _failure(self, kind, *, pid=None, detail=None):
        key = (str(kind), int(pid) if pid is not None else None, str(detail))
        with self._lock:
            if (
                key not in self._failures
                and len(self._failures) >= DEFAULT_MAX_CAPTURE_FAILURES
            ):
                self._failure_overflow_count += 1
                return
            row = self._failures.setdefault(
                key,
                {
                    "kind": str(kind),
                    "pid": int(pid) if pid is not None else None,
                    "detail": str(detail),
                    "count": 0,
                },
            )
            row["count"] += 1

    def attach(self, job):
        """Associate a dedicated completion port while the Job is inactive."""

        if self._closed:
            raise RuntimeError("cannot attach a closed process tracker")
        if self._completion_port_associated:
            raise RuntimeError("process tracker is already attached")
        accounting = job.accounting()
        self._job_inactive_at_association = (
            int(accounting.get("total_processes") or 0) == 0
            and int(accounting.get("active_processes") or 0) == 0
        )
        if not self._job_inactive_at_association:
            raise RuntimeError(
                "completion port must be associated before Job assignment"
            )
        self._job_handle = job.native_handle()
        info = self._completion_port_info_type(
            self._ctypes.c_void_p(self._completion_key),
            self._completion_port,
        )
        if not self._kernel32.SetInformationJobObject(
            self._job_handle,
            7,  # JobObjectAssociateCompletionPortInformation
            self._ctypes.byref(info),
            self._ctypes.sizeof(info),
        ):
            error = self._ctypes.get_last_error()
            raise OSError(error, self._ctypes.FormatError(error))
        self._job = job
        self._completion_port_associated = True
        self._completion_watcher = self._threading.Thread(
            target=self._watch_completion_port,
            name="weather-job-process-lifetime",
            daemon=True,
        )
        self._completion_watcher.start()
        if not self._watcher_ready.wait(timeout=5):
            raise RuntimeError("completion-port watcher did not become ready")
        self._completion_thread_started = True

    def _watch_completion_port(self):
        wait_timeout = 258
        new_process_message = 6
        barrier_message = 0xFFFFFFFE
        stop_message = 0xFFFFFFFF
        self._watcher_ready.set()
        while not self._stop_requested.is_set():
            message = self._wintypes.DWORD()
            completion_key = self._ctypes.c_size_t()
            overlapped = self._ctypes.c_void_p()
            ok = self._kernel32.GetQueuedCompletionStatus(
                self._completion_port,
                self._ctypes.byref(message),
                self._ctypes.byref(completion_key),
                self._ctypes.byref(overlapped),
                250,
            )
            if not ok:
                error = self._ctypes.get_last_error()
                if error == wait_timeout:
                    continue
                if self._stop_requested.is_set():
                    return
                self._failure(
                    "completion_port_read_failed",
                    detail=(
                        f"[WinError {error}] "
                        f"{self._ctypes.FormatError(error)}"
                    ),
                )
                continue
            code = int(message.value)
            key = int(completion_key.value)
            if key == self._sentinel_key and code == stop_message:
                return
            if key == self._sentinel_key and code == barrier_message:
                self._barrier_seen.set()
                continue
            if key != self._completion_key:
                self._failure(
                    "unexpected_completion_key",
                    detail=completion_key.value,
                )
                continue
            with self._lock:
                self._completion_message_counts[code] = (
                    int(self._completion_message_counts.get(code) or 0) + 1
                )
            if code == new_process_message:
                pid = int(overlapped.value or 0)
                self._capture_pid(
                    pid,
                    self._job,
                    source="completion_port_new_process",
                )

    def _post_completion_message(self, message):
        if not self._completion_port:
            return False
        return bool(
            self._kernel32.PostQueuedCompletionStatus(
                self._completion_port,
                int(message),
                self._sentinel_key,
                None,
            )
        )

    def _flush_completion_port(self):
        if not self._completion_thread_started:
            self._failure(
                "completion_thread_not_started",
                detail="tracker was not attached before assignment",
            )
            return False
        self._barrier_seen.clear()
        if not self._post_completion_message(0xFFFFFFFE):
            error = self._ctypes.get_last_error()
            self._failure(
                "completion_barrier_post_failed",
                detail=f"[WinError {error}] {self._ctypes.FormatError(error)}",
            )
            return False
        flushed = self._barrier_seen.wait(timeout=5)
        if not flushed:
            self._failure(
                "completion_barrier_timeout",
                detail="completion watcher did not reach the queue barrier",
            )
        self._completion_queue_flushed = bool(flushed)
        return bool(flushed)

    def _stop_completion_watcher(self):
        watcher = self._completion_watcher
        if watcher is None or not watcher.is_alive():
            return
        self._stop_requested.set()
        self._post_completion_message(0xFFFFFFFF)
        watcher.join(timeout=5)
        if watcher.is_alive():
            self._failure(
                "completion_watcher_join_timeout",
                detail="completion watcher remained alive",
            )

    def _process_times(self, handle):
        values = [self._filetime_type() for _ in range(4)]
        if not self._kernel32.GetProcessTimes(
            handle,
            *(self._ctypes.byref(value) for value in values),
        ):
            error = self._ctypes.get_last_error()
            raise OSError(error, self._ctypes.FormatError(error))
        return {
            "creation_time_100ns": self._filetime_value(values[0]),
            "exit_time_100ns": self._filetime_value(values[1]),
        }

    def _image_path(self, handle):
        buffer = self._ctypes.create_unicode_buffer(32768)
        length = self._wintypes.DWORD(len(buffer))
        if not self._kernel32.QueryFullProcessImageNameW(
            handle,
            0,
            buffer,
            self._ctypes.byref(length),
        ):
            error = self._ctypes.get_last_error()
            raise OSError(error, self._ctypes.FormatError(error))
        return buffer.value

    def _close_unretained_handle(self, handle, *, pid):
        if self._kernel32.CloseHandle(handle):
            return
        error = self._ctypes.get_last_error()
        self._failure(
            "unretained_handle_close_failed",
            pid=pid,
            detail=f"[WinError {error}] {self._ctypes.FormatError(error)}",
        )

    def _process_belongs_to_job(self, handle):
        result = self._wintypes.BOOL()
        if not self._kernel32.IsProcessInJob(
            handle,
            self._job_handle,
            self._ctypes.byref(result),
        ):
            error = self._ctypes.get_last_error()
            raise OSError(error, self._ctypes.FormatError(error))
        return bool(result.value)

    def _capture_pid(self, pid, job, *, source):
        pid = int(pid)
        if pid <= 0:
            self._failure(
                "invalid_process_id",
                pid=pid,
                detail=source,
            )
            return
        with self._lock:
            matching = [
                record
                for identity, record in self._records.items()
                if identity[0] == pid
            ]
            for record in matching:
                wait_result = int(
                    self._kernel32.WaitForSingleObject(
                        record["handle"],
                        0,
                    )
                )
                if wait_result == 258:
                    record["job_membership_observations"] += 1
                    if source not in record["membership_sources"]:
                        record["membership_sources"].append(source)
                    return
                if wait_result not in {0, 258}:
                    if wait_result == 0xFFFFFFFF:
                        error = self._ctypes.get_last_error()
                        detail = (
                            f"[WinError {error}] "
                            f"{self._ctypes.FormatError(error)}"
                        )
                    else:
                        detail = wait_result
                    self._failure(
                        "retained_handle_wait_failed",
                        pid=pid,
                        detail=detail,
                    )
                    return
        handle = self._kernel32.OpenProcess(
            0x1000 | 0x0010 | 0x00100000,
            False,
            pid,
        )
        if not handle:
            if (
                source == "completion_port_new_process"
                and matching
            ):
                with self._lock:
                    self._late_duplicate_notification_count += 1
                    matching[-1]["job_membership_observations"] += 1
                    if source not in matching[-1]["membership_sources"]:
                        matching[-1]["membership_sources"].append(source)
                return
            error = self._ctypes.get_last_error()
            self._failure(
                "open_process_failed",
                pid=pid,
                detail=f"[WinError {error}] {self._ctypes.FormatError(error)}",
            )
            return
        try:
            times = self._process_times(handle)
            image_path = self._image_path(handle)
            job_membership_verified = self._process_belongs_to_job(handle)
        except Exception as exc:
            self._close_unretained_handle(handle, pid=pid)
            self._failure(
                "process_identity_query_failed",
                pid=pid,
                detail=f"{type(exc).__name__}: {exc}",
            )
            return
        if not job_membership_verified:
            self._close_unretained_handle(handle, pid=pid)
            self._failure(
                "process_not_in_job",
                pid=pid,
                detail=source,
            )
            return
        identity = (pid, int(times["creation_time_100ns"]))
        with self._lock:
            existing = self._records.get(identity)
            if existing is not None:
                existing["job_membership_observations"] += 1
                if source not in existing["membership_sources"]:
                    existing["membership_sources"].append(source)
                self._close_unretained_handle(handle, pid=pid)
                return
            if len(self._records) >= self._max_processes:
                self._close_unretained_handle(handle, pid=pid)
                self._failure(
                    "tracker_process_limit_exceeded",
                    pid=pid,
                    detail=self._max_processes,
                )
                return
            self._records[identity] = {
                "pid": pid,
                "handle": handle,
                "creation_time_100ns": times["creation_time_100ns"],
                "image_path": image_path,
                "job_membership_verified": True,
                "job_membership_observations": 1,
                "membership_sources": [source],
                "handle_closed": False,
            }

    def capture(self, job):
        if self._closed:
            self._failure("capture_after_close", detail="tracker closed")
            return
        self._capture_calls += 1
        try:
            process_ids = job.process_ids(capacity=self._max_processes)
        except Exception as exc:
            self._failure(
                "job_process_list_query_failed",
                detail=f"{type(exc).__name__}: {exc}",
            )
            return
        for pid in sorted(set(int(value) for value in process_ids)):
            self._capture_pid(pid, job, source="job_process_id_poll")
        return len(process_ids)

    def has_retained_process(self, pid):
        with self._lock:
            return any(
                int(identity[0]) == int(pid)
                for identity in self._records
            )

    def _terminal_row(self, record):
        row = {
            key: value
            for key, value in record.items()
            if key not in {"handle", "handle_closed"}
        }
        wait_result = int(
            self._kernel32.WaitForSingleObject(record["handle"], 0)
        )
        row["wait_result"] = wait_result
        row["process_exited"] = wait_result == 0
        row["terminal_query_succeeded"] = False
        if not row["process_exited"]:
            if wait_result == 0xFFFFFFFF:
                error = self._ctypes.get_last_error()
                row["terminal_query_error"] = (
                    f"WaitForSingleObject failed: [WinError {error}] "
                    f"{self._ctypes.FormatError(error)}"
                )
                self._failure(
                    "terminal_retained_handle_wait_failed",
                    pid=record["pid"],
                    detail=row["terminal_query_error"],
                )
            else:
                row["terminal_query_error"] = (
                    "process handle is not signaled"
                )
            return row
        try:
            counters = self._memory_counters_type()
            counters.cb = self._ctypes.sizeof(counters)
            if not self._psapi.GetProcessMemoryInfo(
                record["handle"],
                self._ctypes.byref(counters),
                counters.cb,
            ):
                error = self._ctypes.get_last_error()
                raise OSError(error, self._ctypes.FormatError(error))
            times = self._process_times(record["handle"])
        except Exception as exc:
            row["terminal_query_error"] = (
                f"{type(exc).__name__}: {exc}"
            )
            return row
        row.update(
            {
                "terminal_query_succeeded": True,
                "terminal_creation_time_100ns": times[
                    "creation_time_100ns"
                ],
                "creation_time_identity_match": (
                    times["creation_time_100ns"]
                    == record["creation_time_100ns"]
                ),
                "exit_time_100ns": times["exit_time_100ns"],
                "peak_working_set_bytes": int(
                    counters.PeakWorkingSetSize
                ),
                "peak_commit_bytes": int(counters.PeakPagefileUsage),
            }
        )
        return row

    def _wait_for_retained_process_exits(self, *, timeout_seconds=5):
        deadline = time.monotonic() + float(timeout_seconds)
        while True:
            pending = []
            with self._lock:
                records = list(self._records.values())
            for record in records:
                wait_result = int(
                    self._kernel32.WaitForSingleObject(
                        record["handle"],
                        0,
                    )
                )
                if wait_result == 258:
                    pending.append(int(record["pid"]))
                elif wait_result != 0:
                    if wait_result == 0xFFFFFFFF:
                        error = self._ctypes.get_last_error()
                        detail = (
                            f"[WinError {error}] "
                            f"{self._ctypes.FormatError(error)}"
                        )
                    else:
                        detail = wait_result
                    self._failure(
                        "retained_handle_wait_failed",
                        pid=record["pid"],
                        detail=detail,
                    )
            if not pending:
                return True
            if time.monotonic() >= deadline:
                self._failure(
                    "retained_process_exit_timeout",
                    detail=",".join(str(pid) for pid in sorted(pending)),
                )
                return False
            time.sleep(0.02)

    def close(self):
        if self._closed:
            return self._closed_handle_count
        self._stop_completion_watcher()
        self._closed = True
        closed = 0
        with self._lock:
            for record in self._records.values():
                if record.get("handle_closed"):
                    continue
                if self._kernel32.CloseHandle(record["handle"]):
                    record["handle_closed"] = True
                    closed += 1
                else:
                    error = self._ctypes.get_last_error()
                    self._failure(
                        "retained_handle_close_failed",
                        pid=record["pid"],
                        detail=(
                            f"[WinError {error}] "
                            f"{self._ctypes.FormatError(error)}"
                        ),
                    )
            self._closed_handle_count += closed
        if self._completion_port:
            if not self._kernel32.CloseHandle(self._completion_port):
                error = self._ctypes.get_last_error()
                self._failure(
                    "completion_port_close_failed",
                    detail=(
                        f"[WinError {error}] "
                        f"{self._ctypes.FormatError(error)}"
                    ),
                )
            self._completion_port = None
        return self._closed_handle_count

    def finalize(self, accounting):
        self._flush_completion_port()
        self._stop_completion_watcher()
        self._wait_for_retained_process_exits()
        final_accounting = self._job.accounting()
        with self._lock:
            retained_handle_count = len(self._records)
            records = list(self._records.values())
        rows = [self._terminal_row(row) for row in records]
        closed_handle_count = self.close()
        summary = summarize_process_lifetime(
            rows,
            list(self._failures.values()),
            final_accounting,
            retained_handle_count=retained_handle_count,
            closed_handle_count=closed_handle_count,
            max_processes=self._max_processes,
        )
        summary["capture_calls"] = self._capture_calls
        summary["capture_failure_overflow_count"] = (
            self._failure_overflow_count
        )
        summary["late_duplicate_notification_count"] = (
            self._late_duplicate_notification_count
        )
        summary["final_job_accounting"] = dict(final_accounting)
        summary["completion_port"] = {
            "associated": self._completion_port_associated,
            "job_inactive_at_association": (
                self._job_inactive_at_association
            ),
            "watcher_started": self._completion_thread_started,
            "queue_flushed": self._completion_queue_flushed,
            "message_counts": {
                str(key): int(value)
                for key, value in sorted(
                    self._completion_message_counts.items()
                )
            },
            "new_process_message_count": int(
                self._completion_message_counts.get(6) or 0
            ),
            "active_process_zero_message_count": int(
                self._completion_message_counts.get(4) or 0
            ),
        }
        summary["checks"].update({
            "completion_port_associated_before_assignment": bool(
                self._completion_port_associated
                and self._job_inactive_at_association
            ),
            "completion_watcher_started": self._completion_thread_started,
            "completion_queue_flushed": self._completion_queue_flushed,
            "late_duplicate_notifications_bounded": (
                self._late_duplicate_notification_count
                <= self._max_processes
            ),
        })
        if self._failure_overflow_count:
            summary["checks"]["capture_failure_cardinality_bounded"] = False
        summary["status"] = (
            "PASS" if all(summary["checks"].values()) else "FAIL"
        )
        return summary
