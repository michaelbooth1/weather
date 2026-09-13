"""Attempt-local, disk-backed revision selection for settlement audits.

This index is disposable computation, not a settlement ledger or a reusable
cache. Each invocation scans its inputs again in their established order.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sqlite3
import tempfile


MAX_RECORD_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_INDEX_BYTES = 2 * 1024 * 1024 * 1024


class AuditResourceLimit(ValueError):
    """Input or temporary-output bounds prevent a complete audit."""


def iter_csv_rows(path):
    path = Path(path)
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        # DictReader's existing field-size bound also applies to quoted,
        # multiline fields. Bound physical lines before allocating a whole row.
        def lines():
            while line := handle.readline(MAX_RECORD_BYTES + 1):
                if len(line) > MAX_RECORD_BYTES:
                    raise AuditResourceLimit(f"CSV physical line exceeds the audit limit: {path}")
                yield line
        yield from csv.DictReader(lines())


def iter_ledger_rows(root):
    for path in sorted(Path(root).glob("*/ledger.jsonl")):
        with path.open("rb") as handle:
            while line := handle.readline(MAX_RECORD_BYTES + 1):
                if len(line) > MAX_RECORD_BYTES:
                    raise AuditResourceLimit(f"JSONL record exceeds {MAX_RECORD_BYTES} bytes: {path}")
                line = line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    # Retain the existing malformed-line behavior. A valid JSON
                    # value that cannot be a ledger row still raises via dict().
                    continue
                row = dict(value)
                row.setdefault("ledger_path", str(path))
                yield row


class AuditRows:
    """Repeatable row view valid only while its owning AuditStore is open."""

    is_spilled_rows = True

    def __init__(self, store):
        self._store = store

    def __len__(self):
        self._store.require_open()
        return self._store.row_count

    def __iter__(self):
        self._store.require_open()
        cursor = self._store.connection.execute("SELECT payload FROM audited ORDER BY slug")
        try:
            for (payload,) in cursor:
                self._store.check_cancelled()
                yield json.loads(payload)
        finally:
            cursor.close()

    def iter_target_dates(self, target_dates):
        self._store.require_open()
        for target_date in sorted(set(target_dates)):
            cursor = self._store.connection.execute(
                "SELECT payload FROM audited WHERE target_date = ? ORDER BY slug", (target_date,)
            )
            try:
                for (payload,) in cursor:
                    self._store.check_cancelled()
                    yield json.loads(payload)
            finally:
                cursor.close()

    def check_cancelled(self):
        self._store.check_cancelled()

    def verify_lineage(self):
        self._store.check_cancelled()
        self._store.verify_lineage()


class AuditStore:
    def __init__(self, *, scratch_root=None, max_index_bytes=DEFAULT_MAX_INDEX_BYTES,
                 cancelled=None):
        if not isinstance(max_index_bytes, int) or max_index_bytes < 1024 * 1024:
            raise ValueError("The audit index limit must be at least 1 MiB")
        if scratch_root is not None:
            scratch_root = Path(scratch_root)
            scratch_root.mkdir(parents=True, exist_ok=True)
        self._directory = tempfile.TemporaryDirectory(prefix="settlement-audit-", dir=scratch_root)
        self.directory = Path(self._directory.name)
        self.connection = None
        self.cancelled = cancelled
        self.row_count = 0
        self.input_rows = 0
        try:
            self.connection = sqlite3.connect(self.directory / "audit.sqlite3")
            # The cache is bounded in KiB, and neither mmap nor temporary sort
            # tables may grow a process-sized in-memory copy of the corpus.
            self.connection.execute("PRAGMA page_size = 4096")
            self.connection.execute("PRAGMA cache_size = -8192")
            self.connection.execute("PRAGMA mmap_size = 0")
            self.connection.execute("PRAGMA temp_store = FILE")
            actual_limit = self.connection.execute(
                f"PRAGMA max_page_count = {max_index_bytes // 4096}"
            ).fetchone()[0]
            if actual_limit * 4096 > max_index_bytes:
                raise AuditResourceLimit("SQLite did not apply the requested index limit")
            self.connection.executescript("""
                CREATE TABLE revisions (
                    slug TEXT PRIMARY KEY COLLATE BINARY,
                    ledger TEXT,
                    label TEXT
                ) WITHOUT ROWID;
                CREATE TABLE audited (
                    slug TEXT PRIMARY KEY COLLATE BINARY,
                    target_date TEXT NOT NULL,
                    payload TEXT NOT NULL
                ) WITHOUT ROWID;
                CREATE INDEX audited_date ON audited(target_date, slug);
            """)
        except BaseException:
            self.close()
            raise

    def require_open(self):
        if self.connection is None:
            raise RuntimeError("Settlement audit rows were used outside their owning context")

    def check_cancelled(self):
        self.require_open()
        if self.cancelled is not None and self.cancelled():
            raise InterruptedError("Settlement audit cancelled before publication")

    def load(self, labels_csv, ledger_root):
        # Whole-row replacement is essential: an empty value in the last label
        # must not resurrect a nonempty value from an earlier label revision.
        for column, rows in (("label", iter_csv_rows(labels_csv)),
                             ("ledger", iter_ledger_rows(ledger_root))):
            sql = (f"INSERT INTO revisions(slug, {column}) VALUES (?, ?) "
                   f"ON CONFLICT(slug) DO UPDATE SET {column} = excluded.{column}")
            for row in rows:
                self.check_cancelled()
                self.input_rows += 1
                slug = row.get("event_slug")
                if not slug:
                    continue
                if not isinstance(slug, str):
                    raise TypeError("Settlement audit event_slug must be a string")
                self.connection.execute(sql, (slug, json.dumps(row, ensure_ascii=True)))
                if self.input_rows % 512 == 0:
                    self.connection.commit()
            self.connection.commit()

    def merged_rows(self):
        self.require_open()
        cursor = self.connection.execute("SELECT ledger, label FROM revisions ORDER BY slug")
        try:
            for ledger, label in cursor:
                self.check_cancelled()
                merged = json.loads(ledger) if ledger is not None else {}
                for key, value in (json.loads(label) if label is not None else {}).items():
                    if value not in (None, ""):
                        merged[key] = value
                yield merged
        finally:
            cursor.close()

    def add_audited_row(self, row):
        self.check_cancelled()
        self.connection.execute(
            "INSERT INTO audited(slug, target_date, payload) VALUES (?, ?, ?)",
            (row["event_slug"], str(row.get("target_date") or ""), json.dumps(row, ensure_ascii=True)),
        )
        self.row_count += 1
        if self.row_count % 512 == 0:
            self.connection.commit()

    def finish(self):
        self.check_cancelled()
        self.connection.commit()
        return AuditRows(self)

    def close(self):
        try:
            if self.connection is not None:
                self.connection.close()
        finally:
            self.connection = None
            self._directory.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
