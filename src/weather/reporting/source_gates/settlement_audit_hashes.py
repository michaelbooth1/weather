"""Invocation-local hash reuse for explicitly sealed offline lineage inputs.

A caller supplies exact absolute paths and SHA-256 content identities from its
reviewed corpus. Live files outside that set always use a fresh content hash.
The seal is checked against bytes, never just size/mtime, before returning an
audit and again before publishing its authoritative JSON.
"""

from __future__ import annotations

import os
from pathlib import Path
import re


class SealedLineageHashes:
    def __init__(self, store, entries, hash_file):
        self.store = store
        self.hash_file = hash_file
        self.connection = store.connection
        self.connection.execute("""
            CREATE TABLE sealed_lineage (
                path TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0
            ) WITHOUT ROWID
        """)
        for path, digest in entries:
            store.check_cancelled()
            path = Path(path)
            if not path.is_absolute():
                raise ValueError("Sealed lineage identities require absolute paths")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                raise ValueError("Sealed lineage identity requires a SHA-256 digest")
            self.connection.execute(
                "INSERT INTO sealed_lineage(path, sha256) VALUES (?, ?)",
                (self._key(path), digest.lower()),
            )
        self.connection.commit()

    @staticmethod
    def _key(path):
        return os.path.normcase(str(Path(path).resolve()))

    def __call__(self, path):
        self.store.check_cancelled()
        key = self._key(path)
        row = self.connection.execute(
            "SELECT sha256, verified FROM sealed_lineage WHERE path = ?", (key,)
        ).fetchone()
        if row is None:
            return self.hash_file(path)
        expected, verified = row
        if not verified:
            self._verify(key, expected)
            self.connection.execute("UPDATE sealed_lineage SET verified = 1 WHERE path = ?", (key,))
        return expected

    def _verify(self, path, expected):
        self.store.check_cancelled()
        if self.hash_file(path) != expected:
            raise ValueError(f"Sealed lineage content changed: {path}")

    def verify(self):
        self.store.check_cancelled()
        cursor = self.connection.execute("SELECT path, sha256 FROM sealed_lineage ORDER BY path")
        try:
            for path, expected in cursor:
                self._verify(path, expected)
        finally:
            cursor.close()
