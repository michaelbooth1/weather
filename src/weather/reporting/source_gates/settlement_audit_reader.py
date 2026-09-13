"""Bounded reader for the existing audit JSON object and its row array.

Both compact and pretty legacy JSON are supported. The entire document must
validate before a consumer may return a passing gate; a truncated tail never
becomes a valid partial audit.
"""

from __future__ import annotations

import json
from pathlib import Path

from weather.reporting.source_gates.settlement_audit_store import AuditResourceLimit


MAX_VALUE_CHARS = 16 * 1024 * 1024


class _JsonCursor:
    def __init__(self, handle, *, max_value_chars=MAX_VALUE_CHARS, chunk_chars=65536):
        if max_value_chars <= 0 or chunk_chars <= 0:
            raise ValueError("JSON read limits must be positive")
        self.handle = handle
        self.limit = max_value_chars
        self.chunk = min(chunk_chars, max_value_chars)
        self.buffer = ""
        self.position = 0
        self.eof = False
        self.decoder = json.JSONDecoder()

    def _fill(self):
        self.buffer = self.buffer[self.position:]
        self.position = 0
        remaining = self.limit + 1 - len(self.buffer)
        if remaining <= 0:
            raise AuditResourceLimit("Audit JSON value exceeds the bounded reader limit")
        addition = self.handle.read(min(self.chunk, remaining))
        if not addition:
            self.eof = True
        self.buffer += addition

    def peek(self):
        while True:
            while self.position < len(self.buffer) and self.buffer[self.position] in " \t\r\n":
                self.position += 1
            if self.position < len(self.buffer):
                return self.buffer[self.position]
            if self.eof:
                return ""
            self._fill()

    def expect(self, token):
        if self.peek() != token:
            raise ValueError(f"Malformed audit JSON: expected {token!r}")
        self.position += 1

    def value(self):
        if not self.peek():
            raise ValueError("Truncated audit JSON value")
        self.buffer = self.buffer[self.position:]
        self.position = 0
        while True:
            try:
                value, end = self.decoder.raw_decode(self.buffer)
            except json.JSONDecodeError as exc:
                if self.eof:
                    raise ValueError("Malformed or truncated audit JSON value") from exc
            else:
                if end > self.limit:
                    raise AuditResourceLimit("Audit JSON value exceeds the bounded reader limit")
                # A number may end at a chunk edge or inside an unfinished
                # exponent. Wait for its delimiter rather than accepting 1 in 1e3.
                delimited = end < len(self.buffer) and self.buffer[end] in " \t\r\n,]}:"
                if delimited or self.eof:
                    self.position = end
                    return value
            self._fill()


class AuditJsonRows:
    """One-pass stream with bounded scalar metadata populated during iteration."""

    def __init__(self, path, *, max_value_chars=MAX_VALUE_CHARS, chunk_chars=65536):
        self.path = Path(path)
        self.max_value_chars = max_value_chars
        self.chunk_chars = chunk_chars
        self.metadata = {}
        self.row_count = 0
        self.has_fields = False
        self._started = False

    def __iter__(self):
        if self._started:
            raise RuntimeError("Audit JSON rows may only be read once")
        self._started = True
        with self.path.open("r", encoding="utf-8") as handle:
            cursor = _JsonCursor(handle, max_value_chars=self.max_value_chars,
                                 chunk_chars=self.chunk_chars)
            cursor.expect("{")
            seen = set()
            if cursor.peek() != "}":
                while True:
                    key = cursor.value()
                    if not isinstance(key, str) or key in seen or len(seen) >= 64:
                        raise ValueError("Audit JSON has invalid, duplicate or excessive root fields")
                    seen.add(key)
                    self.has_fields = True
                    cursor.expect(":")
                    if key == "rows" and cursor.peek() == "[":
                        cursor.expect("[")
                        if cursor.peek() != "]":
                            while True:
                                row = cursor.value()
                                if not isinstance(row, dict):
                                    raise ValueError("Audit JSON rows must be objects")
                                self.row_count += 1
                                yield row
                                if cursor.peek() == "]":
                                    break
                                cursor.expect(",")
                        cursor.expect("]")
                    else:
                        value = cursor.value()
                        if key == "rows" and value is not None:
                            raise ValueError("Audit JSON rows must be an array or null")
                        if key in {"status", "schema_version", "generated_at_utc"}:
                            if value is not None and not isinstance(value, str):
                                raise ValueError("Audit JSON metadata must be scalar text")
                            self.metadata[key] = value
                    if cursor.peek() == "}":
                        break
                    cursor.expect(",")
            cursor.expect("}")
            if cursor.peek():
                raise ValueError("Audit JSON has trailing content")
