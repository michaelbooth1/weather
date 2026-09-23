"""Single-writer, UTC-day public evidence journal and bounded compression."""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import threading
from datetime import datetime, timezone

from weather.schema_registry import schema_version

SCHEMA = schema_version("maker_evidence")
DEFAULT_STREAM_CAP = 300_000_000


def utc_now():
    return datetime.now(timezone.utc)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(encoded(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def disk_band(free_bytes):
    gib = free_bytes / 1024**3
    return "critical" if gib < 50 else "red" if gib < 60 else "amber" if gib < 75 else "green"


class WriterLock:
    """Kernel lock; an abandoned lock file alone never owns the writer."""
    def __init__(self, root):
        self.path = Path(root) / ".writer.lock"

    def __enter__(self):
        self.handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise RuntimeError("maker evidence already has a writer") from None
        return self

    def __exit__(self, *args):
        self.handle.close()


class EvidenceStore:
    def __init__(self, root, *, stream_cap=DEFAULT_STREAM_CAP, clock=utc_now):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.clock, self.stream_cap = clock, stream_cap
        self.lock = threading.RLock()
        self.day = ""
        self.bytes_written = 0
        self.stream_bytes = 0
        self.stream_capped = False
        self.latest = {}
        self.sequence = 0
        self._roll()

    def _roll(self):
        today = self.clock().date().isoformat()
        if today == self.day:
            return
        if self.day and today < self.day:
            raise RuntimeError("UTC clock moved backwards across day boundary")
        self.day = today
        self.folder = self.root / today
        self.folder.mkdir(exist_ok=True)
        self.stream_bytes, self.sequence = 0, 0
        self.stream_capped, self.latest = False, {}
        manifest = self.folder / "manifest.jsonl"
        if (self.folder / "manifest.jsonl.gz").exists():
            raise RuntimeError("refusing to reopen a compressed evidence day")
        if manifest.exists():
            with manifest.open("rb") as handle:
                for line in handle:
                    row = json.loads(line)  # Torn evidence is an explicit refusal, never truncated.
                    self.sequence = max(self.sequence, row["sequence"])
                    if row.get("kind") == "stream":
                        self.stream_bytes += row["response_bytes"]
                    if row.get("kind") == "stream_cap":
                        self.stream_capped = True
                    if row.get("change_key") and row.get("payload_file"):
                        self.latest[row["change_key"]] = (row["content_sha256"], row["payload_file"], row["payload_offset"])
        # Orphan payload writes after a crash count against the cap too.
        actual = 0
        for stream_file in [self.folder / "stream.jsonl", *self.folder.glob("updates-*.jsonl")]:
            if not stream_file.exists():
                continue
            with stream_file.open("rb") as handle:
                for line in handle:
                    actual += len(base64.b64decode(json.loads(line)["body_base64"], validate=True))
        self.stream_bytes = max(self.stream_bytes, actual)
        self.stream_capped |= self.stream_bytes >= self.stream_cap

    def _append(self, filename, value):
        raw = encoded(value) + b"\n"
        with (self.folder / filename).open("ab") as handle:
            offset = handle.tell()
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        self.bytes_written += len(raw)
        return offset

    def _payload(self, kind, raw):
        """Group books by token without losing a byte of a batched wire reply."""
        if kind not in ("books", "ranking_books"):
            return {"body_base64": base64.b64encode(raw).decode("ascii")}
        try:
            text = raw.decode("utf-8")
            rows = json.loads(text)
        except (UnicodeError, ValueError):
            return {"body_base64": base64.b64encode(raw).decode("ascii")}
        if not isinstance(rows, list) or any(not isinstance(row, dict) or not
                re.fullmatch(r"[0-9]{1,100}", str(row.get("asset_id", ""))) for row in rows):
            return {"body_base64": base64.b64encode(raw).decode("ascii")}
        decoder, parts = json.JSONDecoder(), []
        cursor = text.index("[") + 1
        prior = 0
        for row in rows:
            while text[cursor] in " \r\n\t,":
                cursor += 1
            value, end = decoder.raw_decode(text, cursor)
            if value != row:
                raise ValueError("book-array split changed a value")
            parts.append({"literal_base64": base64.b64encode(text[prior:cursor].encode()).decode()})
            filename = "book-" + str(row["asset_id"]) + ".jsonl"
            offset = self._append(filename, {"sequence": self.sequence,
                       "body_base64": base64.b64encode(text[cursor:end].encode()).decode()})
            parts.append({"file": filename, "offset": offset})
            cursor = prior = end
        parts.append({"literal_base64": base64.b64encode(text[prior:].encode()).decode()})
        return {"parts": parts}

    def record(self, kind, raw, *, metadata=None, change_key=None, stored_body=None, partition=None):
        """Manifest hashes EVERY reply, even when its unchanged body is referenced."""
        with self.lock:
            self._roll()
            if kind == "stream" and self.stream_capped:
                return False
            if kind == "stream" and self.stream_bytes + len(raw) > self.stream_cap:
                self.stream_capped = True
                self.record("stream_cap", encoded({"limit_bytes": self.stream_cap,
                            "retained_bytes": self.stream_bytes, "rejected_frame_bytes": len(raw)}))
                return False
            body = raw if stored_body is None else stored_body
            content_hash = digest(encoded(json.loads(body))) if change_key else digest(body)
            prior = self.latest.get(change_key) if change_key else None
            changed = not prior or prior[0] != content_hash
            self.sequence += 1
            row = {"schema_version": SCHEMA, "sequence": self.sequence,
                   "captured_at_utc": self.clock().isoformat(), "kind": kind,
                   "response_bytes": len(raw), "response_sha256": digest(raw),
                   "stored_sha256": digest(body),
                   "representation": "wire_bytes" if stored_body is None else "selection_projection",
                   "content_sha256": content_hash, "change_key": change_key,
                   "body_stored": changed, **(metadata or {})}
            if changed:
                filename = kind + ".jsonl"
                if partition is not None:
                    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", partition):
                        raise ValueError("invalid evidence partition")
                    filename = kind + "-" + partition + ".jsonl"
                elif kind == "rewards" and change_key:
                    condition = change_key.split(":")[1] if ":" in change_key else ""
                    if re.fullmatch(r"0x[0-9a-fA-F]{64}", condition):
                        filename = "reward-" + condition + ".jsonl"
                elif kind == "stream":
                    try:
                        message = json.loads(raw)
                        condition = message.get("market", "") if isinstance(message, dict) else ""
                        if re.fullmatch(r"0x[0-9a-fA-F]{64}", condition):
                            filename = "updates-" + condition + ".jsonl"
                    except (ValueError, TypeError):
                        pass  # Keep malformed native frames in the generic stream journal.
                offset = self._append(filename, {"sequence": self.sequence, **self._payload(kind, body)})
                if change_key:
                    self.latest[change_key] = (content_hash, filename, offset)
            else:
                _, filename, offset = prior
            row.update(payload_file=filename, payload_offset=offset)
            self._append("manifest.jsonl", row)
            if kind == "stream":
                self.stream_bytes += len(raw)
            return changed

    def event(self, kind, value, *, partition=None):
        return self.record(kind, encoded(value), partition=partition)

    def compress_closed_days(self, stop_event=None):
        """Stream gzip, verify uncompressed SHA, then atomically replace own journal files."""
        with self.lock:
            self._roll()
            today = self.day
        # Only closed days are immutable. Never hold the active writer lock
        # across compression or hash verification of yesterday's large files.
        for folder in sorted(self.root.iterdir()):
            if stop_event is not None and stop_event.is_set():
                return False
            if not folder.is_dir() or len(folder.name) != 10 or folder.name >= today:
                continue
            try:
                datetime.strptime(folder.name, "%Y-%m-%d")
            except ValueError:
                continue
            for path in sorted(folder.glob("*.jsonl")):
                if disk_band(self.free_bytes()) in ("red", "critical"):
                    return False
                zipped = path.with_suffix(".jsonl.gz")
                temporary = path.with_suffix(".jsonl.gz.tmp")
                source_hash = hashlib.sha256()
                if not zipped.exists():
                    with path.open("rb") as source, gzip.open(temporary, "wb", compresslevel=6) as out:
                        while block := source.read(65536):
                            if stop_event is not None and stop_event.is_set():
                                return False
                            source_hash.update(block)
                            out.write(block)
                    with temporary.open("rb+") as durable:
                        os.fsync(durable.fileno())
                    os.replace(temporary, zipped)
                else:
                    with path.open("rb") as source:
                        while block := source.read(65536):
                            if stop_event is not None and stop_event.is_set():
                                return False
                            source_hash.update(block)
                restored_hash = hashlib.sha256()
                with gzip.open(zipped, "rb") as restored:
                    while block := restored.read(65536):
                        if stop_event is not None and stop_event.is_set():
                            return False
                        restored_hash.update(block)
                if restored_hash.digest() != source_hash.digest():
                    raise RuntimeError("closed-day gzip verification failed")
                # This is a representation change, not evidence retention/deletion.
                path.unlink()
        return True

    def free_bytes(self):
        return shutil.disk_usage(self.root).free
