"""Bounded local readers for the maker-plugin diagnostic runner, never collectors."""
from __future__ import annotations

import base64
from collections import Counter
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import time

from weather.market.maker_plugin.inputs import timestamp
from weather.schema_registry import schema_version

MAX_FILE_BYTES = 64 * 1024**2
MAX_ROWS = 100_000


class StopRun(Exception):
    """A resource cap, with partial results still publishable."""


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def regular_path(path, root):
    """Reject redirects, traversal and Windows alternate streams before opening."""
    path, root = Path(path).absolute(), Path(root).absolute()
    if not path.is_relative_to(root):
        raise ValueError("input_path_escape")
    for part in (path, *path.parents):
        if part.exists():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("redirected_path")
        if part != Path(part.anchor) and ":" in part.name:
            raise ValueError("alternate_stream_path")
    if path.resolve() != path:
        raise ValueError("noncanonical_path")
    return path


class Reader:
    def __init__(self, root, max_seconds, max_input_bytes, clock=time.monotonic):
        self.root = Path(root).absolute()
        self.clock, self.started = clock, clock()
        self.max_seconds, self.max_input_bytes = max_seconds, max_input_bytes
        self.bytes_read = 0
        self.coverage = Counter()

    def check(self):
        if self.clock() - self.started >= self.max_seconds:
            raise StopRun("time_cap")

    def read(self, path, limit=MAX_FILE_BYTES):
        self.check()
        path = regular_path(path, self.root)
        before = path.stat()
        opener = gzip.open if path.suffix == ".gz" else open
        chunks, size = [], 0
        # No yielded iterator, cached handle or second open within this context.
        with opener(path, "rb") as handle:
            while True:
                self.check()
                remaining = self.max_input_bytes - self.bytes_read
                if remaining <= 0:
                    raise StopRun("input_byte_cap")
                chunk = handle.read(min(65536, remaining, limit - size + 1))
                self.bytes_read += len(chunk)
                size += len(chunk)
                if size > limit:
                    raise ValueError("file_byte_limit")
                if not chunk:
                    break
                chunks.append(chunk)
        self.check()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError("input_changed_during_read")
        self.coverage["files_read"] += 1
        return b"".join(chunks)

    def variant(self, path):
        regular_path(path, self.root)
        return path if path.is_file() else path.with_name(path.name + ".gz")

    def table(self, path):
        path = self.variant(path)
        if not path.is_file():
            return []
        raw = self.read(path)
        logical = path.name.removesuffix(".gz")
        source = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))) if logical.endswith(".csv") else (
            json.loads(line) for line in raw.splitlines() if line.strip())
        rows = []
        for row in source:
            self.check()
            if not isinstance(row, dict):
                raise ValueError("record_not_object")
            rows.append(row)
            if len(rows) > MAX_ROWS:
                raise ValueError("file_row_limit")
        return rows


class Segment:
    """Only manifested files; hashes/offsets verified before exposing any rows."""
    def __init__(self, reader, folder, manifest):
        self.reader, self.folder, self.manifest = reader, folder, manifest
        self.cache = {}
        self.cache_bytes = 0

    def rows(self, name):
        if not re.fullmatch(r"[a-zA-Z0-9_-]+\.jsonl", name) or name not in self.manifest["files"]:
            raise ValueError("reference_outside_manifest")
        if name in self.cache:
            return self.cache[name]
        expected = self.manifest["files"][name]
        if not 0 <= expected["bytes"] <= MAX_FILE_BYTES:
            raise ValueError("file_byte_limit")
        raw = self.reader.read(self.reader.variant(self.folder / name), expected["bytes"])
        if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
            raise ValueError("sealed_file_hash_or_size_mismatch")
        rows, offset, last = {}, 0, 0
        for line in raw.splitlines(keepends=True):
            self.reader.check()
            row = json.loads(line)
            if not line.endswith(b"\n") or row["offset"] != offset:
                raise ValueError("sealed_record_offset_or_newline")
            rows[offset], last = row, offset
            offset += len(line)
            if len(rows) > MAX_ROWS:
                raise ValueError("file_row_limit")
        if len(rows) != expected["records"] or last != expected["last_offset"]:
            raise ValueError("sealed_record_count_mismatch")
        # Bound the segment cache, including constituent book files.
        if self.cache_bytes + len(raw) > MAX_FILE_BYTES:
            self.cache.clear()
            self.cache_bytes = 0
        self.cache[name] = rows
        self.cache_bytes += len(raw)
        self.reader.coverage["sealed_files_verified"] += 1
        return rows

    def payload(self, row, depth=0):
        self.reader.check()
        if depth > 3:
            raise ValueError("payload_reference_cycle")
        def reference(ref):
            if not isinstance(ref["offset"], int) or ref["offset"] < 0:
                raise ValueError("payload_reference_offset")
            target = self.rows(ref["file"])[ref["offset"]]
            if target["sequence"] > row["sequence"]:
                raise ValueError("future_payload_reference")
            return self.payload(target, depth + 1)
        if "payload_ref" in row:
            raw = reference(row["payload_ref"])
        elif "parts" in row:
            chunks, size = [], 0
            for part in row["parts"]:
                chunk = part["literal_utf8"].encode() if "literal_utf8" in part else reference(part)
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise ValueError("payload_byte_limit")
                chunks.append(chunk)
            raw = b"".join(chunks)
        else:
            raw = row["body_utf8"].encode() if "body_utf8" in row else base64.b64decode(row["body_base64"], validate=True)
        if "kind" in row:
            expected = row.get("stored_sha256", row["response_sha256"])
            canonical = hashlib.sha256(encoded(json.loads(raw))).hexdigest()
            if hashlib.sha256(raw).hexdigest() != expected:
                if row["body_stored"] or canonical != row.get("content_sha256"):
                    raise ValueError("payload_hash_mismatch")
            if row.get("content_sha256") and canonical != row["content_sha256"]:
                raise ValueError("payload_content_hash_mismatch")
        return raw

    def captures(self):
        result = []
        total = 0
        for name in sorted(self.manifest["files"]):
            self.reader.check()
            if name not in ("discovery.jsonl", "books.jsonl", "rewards.jsonl") and not name.startswith("reward-"):
                continue  # No stream, status, ranking-only books or unrelated journals.
            for row in self.rows(name).values():
                self.reader.check()
                if row.get("kind") not in ("discovery", "books", "rewards"):
                    raise ValueError("unexpected_journal_kind")
                if row.get("http_status") != 200:
                    self.reader.coverage[row["kind"] + ".http_failed"] += 1
                    continue
                raw = self.payload(row)
                total += len(raw)
                if total > MAX_FILE_BYTES:
                    raise ValueError("segment_decoded_byte_limit")
                # Preserve the capture clock on unchanged-body references. The
                # decoded projection has its own hash, not a claimed raw reply hash.
                value = dict(row, body_stored=True, body_utf8=raw.decode("utf-8"),
                             response_sha256=hashlib.sha256(raw).hexdigest())
                value.pop("payload_ref", None)
                value.pop("parts", None)
                result.append(value)
                self.reader.coverage[row["kind"] + ".captures"] += 1
                if len(result) > MAX_ROWS:
                    raise ValueError("segment_row_limit")
        return sorted(result, key=lambda r: (timestamp(r["captured_at_utc"]), r["sequence"]))


def sealed_segments(reader, day):
    root = regular_path(reader.root / "maker_evidence" / day, reader.root)
    if not root.is_dir():
        reader.coverage["segments.missing_date"] += 1
        return []
    found = []
    for folder in root.iterdir():
        reader.check()
        if not re.fullmatch(r"(?:[01]\d|2[0-3])-[0-9a-f]{12}", folder.name):
            continue
        regular_path(folder, reader.root)
        manifest_path = reader.variant(folder / "manifest.json")
        if not manifest_path.is_file():
            reader.coverage["segments.unsealed_skipped"] += 1
            continue
        manifest = json.loads(reader.read(manifest_path, 2 * 1024**2))
        if manifest.get("schema_version") != schema_version("maker_evidence"):
            raise ValueError("unsupported_seal_schema")
        sealed = timestamp(manifest["sealed_at_utc"])
        if not isinstance(manifest["files"], dict) or len(manifest["files"]) > 20000:
            raise ValueError("invalid_seal_files")
        found.append((sealed, folder, manifest))
        if len(found) > 2000:
            raise ValueError("segment_count_limit")
    return sorted(found, key=lambda item: (item[0], item[1].name))
