"""Append-only hash-chained journal files for the manual order journal.

One canonical JSON line per run in ``<out>/<UTC-date>.jsonl``. Each line carries
``sequence`` and ``previous_sha256`` (SHA256 of the previous line's bytes), so an
edit, reorder or deletion anywhere breaks verification. Appends read only the
tail; ``verify_chain`` walks everything. Paths are supplied by the caller.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

DAY_FILE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\.jsonl\Z")


class JournalError(RuntimeError):
    """Fixed, data-free failure codes."""


def canonical_line(row):
    return (json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            + "\n").encode("utf-8")


def line_sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def day_files(directory):
    directory = Path(directory)
    if not directory.exists():
        return []
    if directory.is_symlink() or not directory.is_dir():
        raise JournalError("journal_directory_invalid")
    files = sorted(p for p in directory.iterdir() if DAY_FILE.fullmatch(p.name))
    if any(p.is_symlink() or not p.is_file() for p in files):
        raise JournalError("journal_file_invalid")
    return files


def _lines(path):
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise JournalError("journal_tail_truncated")
    return [line + b"\n" for line in raw.split(b"\n")[:-1]]


def _check(raw, sequence, previous):
    try:
        row = json.loads(raw)
    except ValueError:
        raise JournalError("journal_line_unreadable") from None
    if (not isinstance(row, dict) or row.get("sequence") != sequence
            or row.get("previous_sha256") != previous or canonical_line(row) != raw):
        raise JournalError("journal_chain_invalid")
    return row


def read_tail(directory):
    """Return (last_row, last_sha256) after checking only the newest two lines."""
    files = day_files(directory)
    for path in reversed(files):
        lines = _lines(path)
        if not lines:
            raise JournalError("journal_file_empty")
        try:
            row = json.loads(lines[-1])
        except ValueError:
            raise JournalError("journal_line_unreadable") from None
        if not isinstance(row, dict) or canonical_line(row) != lines[-1]:
            raise JournalError("journal_chain_invalid")
        if len(lines) > 1 and row.get("previous_sha256") != line_sha256(lines[-2]):
            raise JournalError("journal_chain_invalid")
        return row, line_sha256(lines[-1])
    return None, None


def verify_chain(directory):
    """Return every record in order, or raise on any break."""
    records, previous = [], None
    for path in day_files(directory):
        lines = _lines(path)
        if not lines:
            raise JournalError("journal_file_empty")
        for raw in lines:
            row = _check(raw, len(records), previous)
            if row.get("recorded_at_utc", "")[:10] + ".jsonl" != path.name:
                raise JournalError("journal_day_mismatch")
            records.append(row)
            previous = line_sha256(raw)
    return records, previous


class WriterLock:
    """OS-held byte lock: released by the kernel if the writer dies."""

    def __init__(self, directory):
        self.path = Path(directory) / ".writer.lock"

    def __enter__(self):
        self.handle = self.path.open("a+b")
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
            raise JournalError("journal_writer_busy") from None
        return self

    def __exit__(self, *args):
        self.handle.close()


def append_record(directory, build):
    """Lock, read the tail, call ``build(tail_row)`` and append its row, chained."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise JournalError("journal_directory_invalid")
    with WriterLock(directory):
        tail, tail_sha = read_tail(directory)
        row = build(tail)
        row["sequence"] = 0 if tail is None else tail["sequence"] + 1
        row["previous_sha256"] = tail_sha
        if tail is not None and row["recorded_at_utc"] <= tail["recorded_at_utc"]:
            raise JournalError("journal_clock_not_monotonic")
        raw = canonical_line(row)
        path = directory / (row["recorded_at_utc"][:10] + ".jsonl")
        with path.open("ab") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        return row, path, line_sha256(raw)
