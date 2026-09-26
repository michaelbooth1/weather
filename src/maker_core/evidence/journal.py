"""Create-only, flushed hash chain lifted from HoldJournal/RE-1 (2b9a0ca9).

Paths are supplied by the caller. No defaults, credentials or domain imports.
A trusted final digest is required to detect tail truncation or whole-chain edits.
"""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
from threading import RLock

from maker_core.contracts import utc_time

SCHEMA_VERSION = "maker_core.journal.v0.1"


def plain(value):
    if is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        if any(not isinstance(k, str) for k in value):
            raise ValueError("canonical mappings require string keys")
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, datetime):
        utc_time(value)
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("nonfinite decimal")
        return str(value)
    return value


def canonical_bytes(value):
    return (json.dumps(plain(value), sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class SecretGuard:
    """Scrub structured auth fields; refuse residual caller-supplied secrets.

    Never loads a secret. Do not journal raw SDK objects or unreviewed payloads.
    """
    def __init__(self, secrets=()):
        self.secrets = tuple(s for s in secrets if s)

    def clean(self, value):
        value = plain(value)
        if isinstance(value, dict):
            value = {k: self.clean(v) for k, v in value.items()
                     if not any(token in re.sub(r"[^a-z0-9]", "", k.lower()) for token in (
                         "key", "secret", "passphrase", "token", "bearer", "mnemonic", "seed", "private",
                         "header", "auth", "signature", "password", "cookie",
                     )) and not (k.lower() == "owner" and isinstance(v, str) and v in self.secrets)}
        elif isinstance(value, list):
            value = [self.clean(v) for v in value]
        encoded = canonical_bytes(value).decode("utf-8")
        if any(s in encoded or json.dumps(s)[1:-1] in encoded for s in self.secrets):
            raise ValueError("secret_output_refused")
        return value


def write_new(path, value, *, guard=None):
    raw = canonical_bytes((guard or SecretGuard()).clean(value))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return hashlib.sha256(raw).hexdigest()


class Journal:
    def __init__(self, path, *, clock, scope, mode="offline", guard=None):
        self.guard = guard or SecretGuard()
        scope = self.guard.clean(scope)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock, self.sequence, self.previous = clock, 0, None
        self.last_time, self.failed = None, False
        self.lock = RLock()
        self.handle = self.path.open("xb")
        try:
            self.record("opened", scope=scope, mode=mode)
        except BaseException:
            self.handle.close()
            self.path.unlink()
            raise

    def record(self, event, **payload):
        with self.lock:
            if self.failed or self.handle.closed:
                raise ValueError("journal unavailable")
            if set(payload) & {"schema_version", "kind", "sequence", "previous_sha256", "recorded_at_utc"}:
                raise ValueError("reserved journal field")
            now = self.clock()
            utc_time(now)
            if self.last_time and now < self.last_time:
                raise ValueError("journal clock regressed")
            row = dict(schema_version=SCHEMA_VERSION, kind="journal", sequence=self.sequence,
                       previous_sha256=self.previous, recorded_at_utc=now,
                       event=event, **self.guard.clean(payload))
            raw = canonical_bytes(self.guard.clean(row))
            try:
                self.handle.write(raw)
                self.handle.flush()
                os.fsync(self.handle.fileno())
            except BaseException:
                self.failed = True
                raise
            self.previous = hashlib.sha256(raw).hexdigest()
            self.sequence += 1
            self.last_time = now
            return self.previous

    def close(self):
        with self.lock:
            self.handle.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def verify_journal(path, *, expected_digest=None, require_terminal=True):
    raw = Path(path).read_bytes()
    if expected_digest is not None and hashlib.sha256(raw).hexdigest() != expected_digest:
        raise ValueError("journal digest differs")
    previous, last, rows = None, None, []
    for index, line in enumerate(raw.splitlines(keepends=True)):
        row = json.loads(line)
        when = datetime.fromisoformat(row["recorded_at_utc"])
        utc_time(when)
        if (canonical_bytes(row) != line or row["sequence"] != index
                or row["previous_sha256"] != previous or row["schema_version"] != SCHEMA_VERSION
                or row["kind"] != "journal" or (last is not None and when < last)):
            raise ValueError("journal chain or clock differs")
        rows.append(row)
        previous, last = hashlib.sha256(line).hexdigest(), when
    if not rows or rows[0]["event"] != "opened":
        raise ValueError("missing opening record")
    if require_terminal and rows[-1]["event"] != "terminal":
        raise ValueError("missing terminal record")
    if any(row["event"] == "terminal" for row in rows[:-1]):
        raise ValueError("records after terminal")
    return tuple(rows)
