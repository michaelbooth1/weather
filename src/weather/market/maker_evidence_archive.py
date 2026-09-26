"""Verified gzip of sealed hourly segments, outside the active writer lock."""
from __future__ import annotations

import gzip
import hashlib
import json
import os

from weather.market.maker_evidence_store import disk_band


def compress_closed_segments(store, stop_event=None):
    if not store.compression_lock.acquire(blocking=False):
        return False
    try:
        for manifest in sorted(store.root.glob("*/*/manifest.json")):
            if stop_event is not None and stop_event.is_set():
                return False
            if disk_band(store.free_bytes()) == "critical":
                return False
            info = json.loads(manifest.read_bytes())
            for name, expected in info["files"].items():
                if not _compress(store, manifest.parent / name, expected["sha256"], stop_event):
                    return False
            if not _compress(store, manifest, hashlib.sha256(manifest.read_bytes()).hexdigest(), stop_event):
                return False
        return True
    finally:
        store.compression_lock.release()


def _compress(store, path, expected_sha, stop_event):
    zipped = path.with_suffix(path.suffix + ".gz")
    temporary = path.with_suffix(path.suffix + ".gz.tmp")
    if not zipped.exists():
        source_hash = hashlib.sha256()
        with path.open("rb") as source, temporary.open("wb") as target:
            with gzip.GzipFile(filename="", mode="wb", fileobj=target, compresslevel=6, mtime=0) as out:
                while block := source.read(65536):
                    if stop_event is not None and stop_event.is_set():
                        return False
                    source_hash.update(block)
                    out.write(block)
            target.flush()
            os.fsync(target.fileno())
        if source_hash.hexdigest() != expected_sha:
            raise ValueError("sealed source hash mismatch")
        os.replace(temporary, zipped)
    restored_hash = hashlib.sha256()
    with gzip.open(zipped, "rb") as restored:
        while block := restored.read(65536):
            if stop_event is not None and stop_event.is_set():
                return False
            restored_hash.update(block)
    if restored_hash.hexdigest() != expected_sha:
        raise ValueError("closed-hour gzip verification failed")
    if path.exists():
        with store.lock:
            size = path.stat().st_size
            path.unlink()  # Verified equivalent representation; no retention deletion.
            store.raw_bytes -= size
    return True
