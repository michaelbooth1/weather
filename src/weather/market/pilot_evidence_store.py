"""Bounded, create-only raw evidence chunks for the independent pilot recorder."""
from __future__ import annotations

import base64
import ctypes
import gzip
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from collections import Counter
from datetime import datetime, timezone

from weather.schema_families import schema_version

VERSION = schema_version("pilot_validation_evidence")
MIB = 1024 * 1024


def stamp():
    return {"receipt_utc": datetime.now(timezone.utc).isoformat(),
            "receipt_monotonic_ns": time.monotonic_ns()}


def rss_bytes():
    """Current resident bytes; fail closed if the platform cannot measure them."""
    if os.name == "nt":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("peak", "working", "pmin", "pmax",
                                             "npmin", "npmax", "page", "peakpage")]

        value = Counters()
        value.cb = ctypes.sizeof(value)
        process = ctypes.windll.kernel32.GetCurrentProcess
        process.restype = wintypes.HANDLE
        query = ctypes.windll.psapi.GetProcessMemoryInfo
        query.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        query.restype = wintypes.BOOL
        if not query(process(), ctypes.byref(value), value.cb):
            raise OSError("RSS measurement unavailable")
        return value.working
    # Linux CI: statm is small and reports current RSS, unlike ru_maxrss.
    return int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")


def source_clocks(value):
    """Keep source fields verbatim; do not manufacture sequence or execution IDs."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"timestamp", "updatedat", "updated_at", "createdat",
                               "block_timestamp", "last_event_at"}:
                found.append({"field": key, "value": item})
            elif isinstance(item, (dict, list)):
                found.extend(source_clocks(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(source_clocks(item))
    return found


class CaptureStopped(Exception):
    """A bounded recorder stop, never a request to retry faster."""


class EvidenceStore:
    """One locked writer, gzip members sealed each minute or four raw MiB.

    Final chunks and their checksum receipts are never reopened. Only health.json
    is replaced. A .partial file after a crash is explicitly unsealed evidence.
    The output cap reserves 64 KiB for the final stop/gap and receipt.
    """

    def __init__(self, root, *, max_output_mib=1536, max_rss_mib=256,
                 memory=rss_bytes, clock=time.monotonic, chunk_bytes=4 * MIB):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=False)
        self.max_bytes = int(max_output_mib * MIB)
        self.max_rss = int(max_rss_mib * MIB)
        self.memory, self.clock = memory, clock
        self.chunk_bytes = chunk_bytes
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.counts, self.gaps = Counter(), Counter()
        self.peak_rss = self.total_bytes = self.raw_bytes = self.chunks = 0
        self.file = self.gz = None
        self.opened = self.clock()
        self.opened_run = self.opened
        self.started = stamp()
        self.reason = None
        self.last_health = 0.0
        self.last_request = None
        self.min_request_spacing = None
        self.end_utc = None

    def fail(self, reason, **details):
        with self.lock:
            if self.reason is None:
                self.reason = reason
                self.gap(reason, **details)
            self.stop.set()

    def check(self):
        if self.stop.is_set():
            raise CaptureStopped(self.reason or "stopped")
        if self.end_utc and datetime.now(timezone.utc) >= self.end_utc:
            self.reason = "end_utc"
            self.stop.set()
            raise CaptureStopped("end_utc")
        if (self.root / "STOP").exists():
            self.fail("operator_stop_file")
            raise CaptureStopped("operator_stop_file")
        current = self.memory()
        self.peak_rss = max(self.peak_rss, current)
        if current >= self.max_rss:
            self.fail("rss_cap", rss_bytes=current)
            raise CaptureStopped("rss_cap")

    def gap(self, code, **details):
        with self.lock:
            self.gaps[code] += 1
            self.write("gap", {"code": code, **details}, control=True)

    def write(self, kind, payload, *, received=None, control=False):
        with self.lock:
            if not control:
                self.check()
            row = {"schema_version": VERSION, "kind": kind,
                   **(received or stamp()), **payload}
            encoded = (json.dumps(row, separators=(",", ":"), ensure_ascii=True,
                                  allow_nan=False) + "\n").encode()
            if len(encoded) > 8 * MIB:
                self.fail("record_size_cap", bytes=len(encoded))
                raise CaptureStopped("record_size_cap")
            # gzip can expand incompressible input slightly. Reserve before write.
            used = self.total_bytes + (self.file.tell() if self.file else 0)
            if not control and used + len(encoded) + 65536 >= self.max_bytes:
                self.fail("output_cap", bytes=used)
                raise CaptureStopped("output_cap")
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

    def raw(self, kind, body, *, received=None, **details):
        try:
            parsed = json.loads(body)
        except (ValueError, UnicodeError):
            parsed = None
        self.write(kind, {**details, "body_base64": base64.b64encode(body).decode("ascii"),
                          "body_sha256": hashlib.sha256(body).hexdigest(),
                          "source_timestamps": source_clocks(parsed)}, received=received)
        return parsed

    def seal(self):
        with self.lock:
            if self.file is None:
                return
            self.gz.close()
            self.file.flush()
            os.fsync(self.file.fileno())
            self.file.close()
            final = self.partial.with_suffix("")
            # Exclusive hard link publishes without overwriting an existing chunk.
            os.link(self.partial, final)
            self.partial.unlink()
            digest = hashlib.sha256()
            with final.open("rb") as stream:
                for block in iter(lambda: stream.read(65536), b""):
                    digest.update(block)
            receipt = {"file": final.name, "sha256": digest.hexdigest(),
                       "bytes": final.stat().st_size, "raw_bytes": self.raw_bytes,
                       **stamp()}
            receipt_bytes = (json.dumps(receipt) + "\n").encode()
            with final.with_suffix(final.suffix + ".sha256.json").open("xb") as stream:
                stream.write(receipt_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            self.total_bytes += receipt["bytes"] + len(receipt_bytes)
            self.chunks += 1
            self.file = self.gz = None

    def request_started(self, monotonic):
        with self.lock:
            if self.last_request is not None:
                spacing = monotonic - self.last_request
                self.min_request_spacing = (spacing if self.min_request_spacing is None else
                                            min(spacing, self.min_request_spacing))
            self.last_request = monotonic
            self.counts["rest_requests"] += 1

    def health(self, *, final=False):
        with self.lock:
            elapsed = max(0.001, self.clock() - self.opened_run)
            receipt = {"schema_version": VERSION, **stamp(), "started": self.started,
                       "final": final, "stop_reason": self.reason,
                       "counts": dict(self.counts), "gaps": dict(self.gaps),
                       "sealed_chunks": self.chunks, "peak_rss_bytes": self.peak_rss,
                       "output_bytes": self.total_bytes + (self.file.tell() if self.file else 0),
                       "elapsed_seconds": elapsed,
                       "rest_average_rps": self.counts["rest_requests"] / elapsed,
                       "rest_min_spacing_seconds": self.min_request_spacing}
            temp = self.root / "health.json.tmp"
            temp.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            temp.replace(self.root / "health.json")
            return receipt

    def start(self, manifest):
        self.opened_run = self.clock()
        self.write("manifest", manifest)
        self.health()

    def close(self, reason):
        with self.lock:
            self.reason = self.reason or reason
            self.write("stop", {"reason": self.reason}, control=True)
            self.seal()
            return self.health(final=True)
