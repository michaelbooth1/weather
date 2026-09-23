"""Hourly public journals: inline offsets/hashes, file manifests, hard raw limit."""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
from datetime import datetime, timezone
from uuid import uuid4

from weather.schema_registry import schema_version

SCHEMA = schema_version("maker_evidence")
DEFAULT_STREAM_CAP = 300_000_000
MAX_RAW_BYTES = 500_000_000
ROTATE_BYTES = 100_000_000
MAX_LINE_BYTES = 16 * 1024**2


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


def inline_body(raw):
    try:
        return {"body_utf8": raw.decode("utf-8")}
    except UnicodeError:
        return {"body_base64": base64.b64encode(raw).decode("ascii")}


def decode_body(row):
    return row["body_utf8"].encode("utf-8") if "body_utf8" in row else base64.b64decode(row["body_base64"], validate=True)


class RawFootprintLimit(RuntimeError):
    pass


class WriterLock:
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
    def __init__(self, root, *, stream_cap=DEFAULT_STREAM_CAP, clock=utc_now,
                 max_raw_bytes=MAX_RAW_BYTES, rotate_bytes=ROTATE_BYTES):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.clock, self.stream_cap = clock, stream_cap
        self.max_raw_bytes, self.rotate_bytes = max_raw_bytes, rotate_bytes
        self.lock, self.compression_lock = threading.RLock(), threading.Lock()
        self.day, self.hour, self.folder = "", "", None
        self.bytes_written = self.raw_bytes = self.peak_raw_bytes = 0
        self.stream_bytes, self.stream_capped = 0, False
        self.failure = None
        self.files, self.latest, self.subscriptions = {}, {}, {}
        self.sequence = self.segment_bytes = 0
        self._recover()
        self._roll()

    def _recover(self):
        """Seal interrupted v2 segments; never truncate or rewrite a journal."""
        if any(self.root.glob("*/manifest.jsonl*")):
            raise ValueError("legacy daily journals require a separate v2 root; no in-place migration")
        paths = list(self.root.glob("*/*/*.jsonl")) + list(self.root.glob("*/*/manifest.json"))
        self.raw_bytes = sum(p.stat().st_size for p in paths)
        self.peak_raw_bytes = self.raw_bytes
        if len(paths) > 20000 or self.raw_bytes >= self.max_raw_bytes:
            raise RawFootprintLimit("existing uncompressed journals exceed startup bound")
        today = self.clock().date().isoformat()
        for folder in sorted(self.root.glob("*/*")):
            if not folder.is_dir() or not re.fullmatch(r"\d{2}-[0-9a-f]{12}", folder.name):
                continue
            manifest = folder / "manifest.json"
            zipped = folder / "manifest.json.gz"
            if manifest.exists() or zipped.exists():
                opener, path = (open, manifest) if manifest.exists() else (gzip.open, zipped)
                with opener(path, "rb") as handle:
                    info = json.load(handle)
                if info["schema_version"] != SCHEMA:
                    raise ValueError("unsupported journal schema")
            else:
                self.folder, self.files = folder, {}
                for path in folder.glob("*.jsonl"):
                    stats = self._new_stats()
                    with path.open("rb") as handle:
                        while line := handle.readline(MAX_LINE_BYTES + 1):
                            if len(line) > MAX_LINE_BYTES:
                                raise ValueError("oversized interrupted journal record")
                            row = json.loads(line)
                            if row["offset"] != stats["bytes"] or not line.endswith(b"\n"):
                                raise ValueError("torn journal or invalid record offset")
                            self._update_stats(stats, line, row)
                    self.files[path.name] = stats
                info = self._seal()
            if folder.parent.name == today:
                self.stream_bytes += info["stream_response_bytes"]
                self.stream_capped |= info["stream_capped"]
        self.day = today
        self.folder, self.files = None, {}
        self.stream_capped |= self.stream_bytes >= self.stream_cap

    @staticmethod
    def _new_stats():
        return {"hash": hashlib.sha256(), "bytes": 0, "records": 0,
                "stream_response_bytes": 0, "stream_capped": False, "last_offset": 0}

    @staticmethod
    def _update_stats(stats, raw, row):
        stats["hash"].update(raw)
        stats["bytes"] += len(raw)
        stats["records"] += 1
        stats["last_offset"] = row["offset"]
        if row.get("kind") == "stream":
            stats["stream_response_bytes"] += row["response_bytes"]
        stats["stream_capped"] |= row.get("kind") == "stream_cap"

    def _roll(self):
        now = self.clock()
        day, hour = now.date().isoformat(), now.strftime("%Y-%m-%dT%H")
        if self.day and day < self.day or self.hour and hour < self.hour:
            raise RuntimeError("UTC clock moved backwards across journal boundary")
        if self.folder is not None and self.hour == hour and self.segment_bytes < self.rotate_bytes:
            return
        self._seal()
        if self.day != day:
            self.stream_bytes, self.stream_capped = 0, False
        self.day, self.hour = day, hour
        self.folder = self.root / day / (now.strftime("%H") + "-" + uuid4().hex[:12])
        self.folder.mkdir(parents=True)
        self.files, self.latest, self.subscriptions = {}, {}, {}
        self.sequence = self.segment_bytes = 0

    def _account(self, amount, *, reserve=True):
        limit = self.max_raw_bytes - (min(1_000_000, self.max_raw_bytes // 10) if reserve else 0)
        if self.raw_bytes + amount >= limit:
            self.failure = "uncompressed journal footprint limit"
            raise RawFootprintLimit(self.failure)

    def _append(self, filename, value):
        stats = self.files.get(filename) or self._new_stats()
        row = {**value, "offset": stats["bytes"]}
        raw = encoded(row) + b"\n"
        self._account(len(raw))
        with (self.folder / filename).open("ab") as handle:
            if handle.tell() != row["offset"]:
                raise ValueError("journal changed outside writer")
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        self._update_stats(stats, raw, row)
        self.files[filename] = stats
        self.raw_bytes += len(raw)
        self.peak_raw_bytes = max(self.peak_raw_bytes, self.raw_bytes)
        self.bytes_written += len(raw)
        self.segment_bytes += len(raw)
        return row["offset"]

    def _payload(self, kind, raw):
        if kind not in ("books", "ranking_books"):
            return inline_body(raw)
        try:
            text, rows = raw.decode("utf-8"), json.loads(raw)
        except (UnicodeError, ValueError):
            return inline_body(raw)
        if not isinstance(rows, list) or len(rows) > 100 or any(not isinstance(r, dict) or not
                re.fullmatch(r"[0-9]{1,100}", str(r.get("asset_id", ""))) for r in rows):
            return inline_body(raw)
        decoder, parts, cursor, prior = json.JSONDecoder(), [], text.index("[") + 1, 0
        for row in rows:
            while text[cursor] in " \r\n\t,":
                cursor += 1
            value, end = decoder.raw_decode(text, cursor)
            if value != row:
                raise ValueError("book-array split changed a value")
            parts.append({"literal_utf8": text[prior:cursor]})
            filename = "book-" + str(row["asset_id"]) + ".jsonl"
            offset = self._append(filename, {"sequence": self.sequence, "body_utf8": text[cursor:end]})
            parts.append({"file": filename, "offset": offset})
            cursor = prior = end
        parts.append({"literal_utf8": text[prior:]})
        return {"parts": parts}

    def record(self, kind, raw, *, metadata=None, change_key=None, stored_body=None, partition=None):
        with self.lock:
            self._roll()
            if kind == "stream" and self.stream_capped:
                return False
            if kind == "stream" and self.stream_bytes + len(raw) > self.stream_cap:
                self.stream_capped = True
                self.event("stream_cap", {"limit_bytes": self.stream_cap, "retained_bytes": self.stream_bytes})
                return False
            body = raw if stored_body is None else stored_body
            content_hash = digest(encoded(json.loads(body))) if change_key else digest(body)
            prior = self.latest.get(change_key) if change_key else None
            changed = not prior or prior[0] != content_hash
            self.sequence += 1
            row = {"sequence": self.sequence, "captured_at_utc": self.clock().isoformat(),
                   "kind": kind, "response_bytes": len(raw), "response_sha256": digest(raw),
                   "body_stored": changed, **(metadata or {})}
            if change_key:
                row.update(change_key=change_key, content_sha256=content_hash)
            if stored_body is not None:
                row.update(representation="selection_projection", stored_sha256=digest(body))
            filename = kind + ".jsonl"
            if partition is not None:
                if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", partition):
                    raise ValueError("invalid evidence partition")
                filename = kind + "-" + partition + ".jsonl"
            elif kind == "rewards" and change_key:
                filename = "reward-" + digest(change_key.encode())[:24] + ".jsonl"
            elif kind == "stream":
                try:
                    message = json.loads(raw)
                    condition = message.get("market", "") if isinstance(message, dict) else ""
                    if re.fullmatch(r"0x[0-9a-fA-F]{64}", condition):
                        filename = "updates-" + condition + ".jsonl"
                except (ValueError, TypeError):
                    pass
            if changed:
                row.update(self._payload(kind, body))
            else:
                row["payload_ref"] = {"file": prior[1], "offset": prior[2]}
            offset = self._append(filename, row)
            if changed and change_key:
                self.latest[change_key] = (content_hash, filename, offset)
            if kind == "stream":
                self.stream_bytes += len(raw)
            return changed

    def event(self, kind, value, *, partition=None):
        return self.record(kind, encoded(value), partition=partition)

    def subscription(self, tokens, channel):
        """Internal subscription content once per unique set in each rotated segment."""
        with self.lock:
            self._roll()
            value = {"channel": channel, "tokens": list(tokens)}
            key = digest(encoded(value))
            if key not in self.subscriptions:
                self.record("subscription", encoded(value), partition=key[:24])
                self.subscriptions[key] = {"file": "subscription-" + key[:24] + ".jsonl", "offset": 0}
            return {"sha256": key, "segment": str(self.folder.relative_to(self.root)).replace("\\", "/"),
                    **self.subscriptions[key]}

    def _seal(self):
        if self.folder is None:
            return None
        files = {name: {key: value for key, value in stats.items() if key != "hash"}
                 | {"sha256": stats["hash"].hexdigest()} for name, stats in self.files.items()}
        info = {"schema_version": SCHEMA, "sealed_at_utc": self.clock().isoformat(), "files": files,
                "stream_response_bytes": sum(s["stream_response_bytes"] for s in files.values()),
                "stream_capped": any(s["stream_capped"] for s in files.values())}
        size = len(encoded(info)) + 1
        self._account(size, reserve=False)
        atomic_json(self.folder / "manifest.json", info)
        self.raw_bytes += size
        self.peak_raw_bytes = max(self.peak_raw_bytes, self.raw_bytes)
        self.folder = None
        return info

    def seal(self):
        with self.lock:
            return self._seal()

    def maintenance(self, stop_event=None):
        from weather.market.maker_evidence_archive import compress_closed_segments
        with self.lock:
            self._roll()
        return compress_closed_segments(self, stop_event)

    def free_bytes(self):
        return shutil.disk_usage(self.root).free
