"""Bounded raw chunks, failure-safe finalization and price-free health snapshots."""
from __future__ import annotations

import base64
from collections import Counter
from contextlib import contextmanager
import ctypes
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import time
from datetime import datetime, timezone

from weather.market.pilot_evidence_contract import MIB, strict_json
from weather.market.pilot_evidence_health import BANK_BYTES, HealthFile
from weather.schema_families import schema_version

VERSION = schema_version("pilot_validation_evidence")


def stamp():
    return {"receipt_utc": datetime.now(timezone.utc).isoformat(),
            "receipt_monotonic_ns": time.monotonic_ns()}


def process_memory(pid=None, handle=None):
    if os.name == "nt":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("peak", "working", "pmin", "pmax",
                                             "npmin", "npmax", "page", "peakpage")]
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        owned_handle = pid is not None and handle is None
        handle = handle or (kernel.OpenProcess(0x410, False, pid) if pid else kernel.GetCurrentProcess())
        if not handle:
            raise OSError("process RSS unavailable")
        try:
            value = Counters()
            value.cb = ctypes.sizeof(value)
            query = ctypes.windll.psapi.GetProcessMemoryInfo
            query.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
            query.restype = wintypes.BOOL
            if not query(handle, ctypes.byref(value), value.cb):
                raise OSError("RSS measurement unavailable")
            return value.working, value.peak
        finally:
            if owned_handle:
                kernel.CloseHandle(handle)
    path = Path(f"/proc/{pid or 'self'}/statm")
    current = int(path.read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    return current, current


def rss_bytes():
    return process_memory()[0]


def source_clocks(value):
    pending, found = [value], []
    while pending:
        row = pending.pop()
        if isinstance(row, dict):
            for key, item in row.items():
                if key.lower() in {"timestamp", "updatedat", "updated_at", "createdat",
                                   "block_timestamp", "last_event_at"}:
                    found.append({"field": key, "value": item})
                elif isinstance(item, (dict, list)):
                    pending.append(item)
        elif isinstance(row, list):
            pending.extend(item for item in row if isinstance(item, (dict, list)))
    return found


class CaptureStopped(Exception):
    """A bounded recorder stop; never permission to retry faster."""


class EvidenceStore:
    def __init__(self, root, *, max_output_mib=4096, max_rss_mib=256,
                 memory=rss_bytes, clock=time.monotonic, chunk_bytes=4 * MIB,
                 free_space=None, min_free_gib=40, existing_root=False,
                 health_sink=None, cancel=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=existing_root)
        self.max_bytes, self.max_rss = int(max_output_mib * MIB), int(max_rss_mib * MIB)
        self.memory, self.clock, self.chunk_bytes = memory, clock, chunk_bytes
        disk_root = Path("C:/") if os.name == "nt" else self.root
        self.free_space = free_space or (lambda: shutil.disk_usage(disk_root).free)
        self.min_free = int(min_free_gib * 1024 ** 3)
        self.last_free = 0
        self.lock, self.stop = threading.RLock(), threading.Event()
        self.cancel = cancel
        self.counts, self.gaps, self.secondary_errors = Counter(), Counter(), Counter()
        self.byte_counts, self.max_body_bytes = Counter(), Counter()
        self.peak_rss = self.total_bytes = self.raw_bytes = self.chunks = 0
        self.file = self.gz = None
        self.opened = self.opened_run = self.clock()
        self.last_heartbeat = self.opened_run
        self.active_at = None
        self.started = stamp()
        self.reason = None
        self.last_request = self.min_request_spacing = None
        self.last_network = self.min_network_spacing = None
        self.last_attempt = self.min_attempt_spacing = None
        self.last_network_stamp, self.operations = {}, {}
        self.end_utc = self.plan = None
        self.coverage = lambda: {}
        self.health_file = HealthFile(self.root) if health_sink is None else None
        self.health_sink = health_sink or self.health_file.write
        self.storage_failed = self.closed = False
        self.last_resource_check = -1e99
        self.final_receipt = None

    def storage_error(self, stage):
        self.stop.set()
        self.reason = self.reason or "storage_failure"
        self.storage_failed = True
        self.secondary_errors[stage] += 1
        self.gaps["storage_failure"] += 1
        self.health()  # Independent sink first; never recurse into the chunk writer.

    def fail(self, reason, **details):
        self.stop.set()  # Before any serialization or I/O.
        with self.lock:
            self.reason = self.reason or reason
            self.gaps[reason] += 1
            if self.reason != reason:
                self.secondary_errors[reason] += 1
            self.health()
            if not self.storage_failed:
                try:
                    self.write("gap", {"code": reason, **details}, control=True)
                except (OSError, CaptureStopped):
                    self.storage_error("failure_journal")

    def check(self, *, fast=False):
        if self.stop.is_set():
            raise CaptureStopped(self.reason or "stopped")
        if self.cancel is not None and self.cancel.value:
            if self.cancel.value == 1:
                self.reason = "end_utc"
                self.stop.set()
                raise CaptureStopped("end_utc")
            self.fail("supervisor_stop")
            raise CaptureStopped("supervisor_stop")
        if self.plan:
            delta = self.plan.check_clock()
            if delta is not None:
                self.fail("clock_discontinuity", delta_seconds=delta)
                raise CaptureStopped("clock_discontinuity")
            if self.plan.end_at is not None and self.clock() >= self.plan.end_at:
                self.reason = "end_utc"
                self.stop.set()
                raise CaptureStopped("end_utc")
        if (self.root / "STOP").exists():
            self.fail("operator_stop_file")
            raise CaptureStopped("operator_stop_file")
        if fast and self.clock() - self.last_resource_check < 0.25:
            return
        self.last_resource_check = self.clock()
        self.peak_rss = max(self.peak_rss, self.memory())
        if self.peak_rss >= self.max_rss:
            self.fail("rss_cap", rss_bytes=self.peak_rss)
            raise CaptureStopped("rss_cap")
        self.last_free = self.free_space()
        if self.last_free < self.min_free:
            self.fail("free_space_floor", free_bytes=self.last_free, floor_bytes=self.min_free)
            raise CaptureStopped("free_space_floor")
        if not fast and self.clock() - self.last_heartbeat >= 1:
            self.health()  # A shared Retry-After wait is alive, not a hung worker.

    def gap(self, code, **details):
        with self.lock:
            self.gaps[code] += 1
            self.write("gap", {"code": code, **details}, control=True)

    def write(self, kind, payload, *, received=None, control=False):
        with self.lock:
            if not control:
                self.check()
            if self.storage_failed:
                raise CaptureStopped("storage_failure")
            row = {"schema_version": VERSION, "kind": kind, **(received or stamp()), **payload}
            encoded = (json.dumps(row, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode()
            if len(encoded) > 8 * MIB:
                self.fail("record_size_cap", bytes=len(encoded))
                raise CaptureStopped("record_size_cap")
            used = self.total_bytes + 2 * BANK_BYTES + (self.file.tell() if self.file else 0)
            if not control and used + len(encoded) + 65536 >= self.max_bytes:
                self.fail("output_cap", bytes=used)
                raise CaptureStopped("output_cap")
            try:
                if self.file is None:
                    self.partial = self.root / f"chunk-{self.chunks:06d}.jsonl.gz.partial"
                    self.file = self.partial.open("xb")
                    self.gz = gzip.GzipFile(filename="", mode="wb", fileobj=self.file, mtime=0)
                    self.opened, self.raw_bytes = self.clock(), 0
                self.gz.write(encoded)
                self.gz.flush()
                self.raw_bytes += len(encoded)
                self.counts[kind] += 1
                if self.raw_bytes >= self.chunk_bytes or self.clock() - self.opened >= 60:
                    self.seal()
            except OSError:
                self.storage_error("chunk_write")
                raise CaptureStopped("storage_failure") from None

    def raw(self, kind, body, *, received=None, parse=True, **details):
        # Retain exact bytes BEFORE parsing, source-clock extraction or validation.
        digest = hashlib.sha256(body).hexdigest()
        self.write(kind, {**details, "body_base64": base64.b64encode(body).decode("ascii"),
                          "body_sha256": digest}, received=received)
        self.byte_counts[kind] += len(body)
        self.max_body_bytes[kind] = max(self.max_body_bytes[kind], len(body))
        self.check()
        if not parse:
            return None
        try:
            parsed = strict_json(body)
        except (ValueError, UnicodeError, RecursionError):
            self.gap("raw_json_unvalidated", body_sha256=digest)
            return None
        clocks = source_clocks(parsed)
        if clocks:
            self.write("source_clocks", {"body_sha256": digest, "source_timestamps": clocks},
                       received=received)
        return parsed

    def seal(self):
        with self.lock:
            if self.file is None or self.storage_failed:
                return
            try:
                self.gz.close()
                self.file.flush()
                os.fsync(self.file.fileno())
                self.file.close()
                final = self.partial.with_suffix("")
                os.link(self.partial, final)
                digest = hashlib.sha256()
                with final.open("rb") as stream:
                    for block in iter(lambda: stream.read(65536), b""):
                        digest.update(block)
                receipt = {"file": final.name, "sha256": digest.hexdigest(),
                           "bytes": final.stat().st_size, "raw_bytes": self.raw_bytes, **stamp()}
                raw = (json.dumps(receipt) + "\n").encode()
                with final.with_suffix(final.suffix + ".sha256.json").open("xb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Receipt is durable before dropping the partial name.
                self.partial.unlink()
                self.total_bytes += receipt["bytes"] + len(raw)
                self.chunks += 1
                self.file = self.gz = None
            except OSError:
                self.storage_error("seal")
                raise CaptureStopped("storage_failure") from None

    def request_started(self, monotonic):
        if self.last_request is not None:
            spacing = monotonic - self.last_request
            self.min_request_spacing = spacing if self.min_request_spacing is None else min(spacing, self.min_request_spacing)
        self.last_request = monotonic
        self.counts["rest_requests"] += 1

    def network_started(self, kind, monotonic=None):
        with self.lock:
            now = self.clock() if monotonic is None else monotonic
            if self.last_network is not None:
                delta = now - self.last_network
                self.min_network_spacing = delta if self.min_network_spacing is None else min(delta, self.min_network_spacing)
            self.last_network = now
            self.last_network_stamp[kind] = stamp()
            self.counts["network_starts"] += 1
            if kind == "rest":
                self.request_started(now)
            else:
                self.counts[kind] += 1

    def attempt_started(self, kind):
        with self.lock:
            now = self.clock()
            if self.last_attempt is not None:
                delta = now - self.last_attempt
                self.min_attempt_spacing = delta if self.min_attempt_spacing is None else min(delta, self.min_attempt_spacing)
            self.last_attempt = now
            self.counts["transport_attempts"] += 1
            self.counts["attempt_" + kind] += 1

    def begin_operation(self, name, seconds):
        with self.lock:
            self.operations[name] = {"started_monotonic": self.clock(), "deadline_monotonic": self.clock() + seconds}
            self.health()

    def end_operation(self, name):
        with self.lock:
            self.operations.pop(name, None)
            self.health()

    @contextmanager
    def operation(self, name, seconds):
        self.begin_operation(name, seconds)
        try:
            yield
        finally:
            self.end_operation(name)

    def health(self, *, final=False):
        with self.lock:
            now = self.clock()
            self.last_heartbeat = now
            active = max(0.001, now - self.active_at) if self.active_at is not None else None
            opened_bytes = 0
            try:
                opened_bytes = self.file.tell() if self.file and not self.file.closed else 0
            except OSError:
                pass
            receipt = {"schema_version": VERSION, **stamp(), "started": self.started,
                       "final": final, "stop_reason": self.reason, "counts": dict(self.counts),
                       "gaps": dict(self.gaps), "secondary_errors": dict(self.secondary_errors),
                       "raw_body_bytes_by_kind": dict(self.byte_counts),
                       "max_raw_body_bytes_by_kind": dict(self.max_body_bytes),
                       "storage_failed": self.storage_failed, "sealed_chunks": self.chunks,
                       "sampled_peak_rss_bytes": self.peak_rss, "peak_rss_bytes": self.peak_rss,
                       "output_bytes_excluding_worker_status": self.total_bytes + opened_bytes + 2 * BANK_BYTES,
                       "output_bytes": self.total_bytes + opened_bytes + 2 * BANK_BYTES,
                       "elapsed_seconds": now - self.opened_run, "active_seconds": active,
                       "rest_average_rps": self.counts["rest_requests"] / active if active else 0,
                       "network_average_rps": self.counts["network_starts"] / active if active else 0,
                       "rest_min_spacing_seconds": self.min_request_spacing,
                       "network_min_spacing_seconds": self.min_network_spacing,
                       "transport_attempt_min_spacing_seconds": self.min_attempt_spacing,
                       "free_disk_bytes": self.last_free, "operations": dict(self.operations),
                       "coverage": self.coverage(), "native_sequence_completeness_proven": False}
            self.health_sink(receipt)
            return receipt

    def start(self, manifest):
        self.opened_run = self.clock()
        self.health()  # Reserve/starting receipt precedes the first chunk.
        self.write("manifest", manifest)
        self.health()

    def close(self, reason):
        with self.lock:
            if self.closed:
                return self.final_receipt
            self.reason = self.reason or reason
            self.health()  # Always before final stop/chunk sealing.
            try:
                if not self.storage_failed:
                    self.write("stop", {"reason": self.reason}, control=True)
                    self.seal()
            except (OSError, CaptureStopped):
                self.storage_error("finalization")
            finally:
                for resource in (self.gz, self.file):
                    if resource is not None:
                        try:
                            resource.close()
                        except OSError:
                            self.secondary_errors["close"] += 1
                self.file = self.gz = None
            self.closed = True
            self.final_receipt = self.health(final=True)
            if self.health_file:
                self.health_file.close()
            return self.final_receipt
