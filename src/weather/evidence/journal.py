"""PL-1 evidence journal: one writer per family, change-only rows, sealed and chained segments.

Layout under the evidence root (``data/evidence`` by default)::

    <family>/<utc_day>/<HH>-<12 hex>/<partition>.jsonl      open segment (plain)
    <family>/<utc_day>/<HH>-<12 hex>/<partition>.jsonl.gz   sealed (gzip-6, verified)
    <family>/<utc_day>/<HH>-<12 hex>/manifest.json          sha256/bytes/records per file
    <family>/<utc_day>/day_seal.json                        daily seal, chained by prev_seal_sha256
    cas/sha256/<ab>/<sha256>.blob                           raw bytes, stored once

Rules (plan §2): bodies are change-only per ``(channel, key)``; every poll writes one heartbeat
row so "unchanged" and "not captured" never look alike; caps and gaps are rows in the journal;
segments rotate hourly or at ``rotate_bytes`` and are gzipped at seal, the plain file removed only
after the gzip decompresses to the recorded sha256. Nothing is ever truncated or rewritten: a torn
tail after a crash is sealed as found and flagged ``torn_tail``.
"""
from __future__ import annotations

import gzip
import hashlib
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from weather.evidence.envelope import canonical, sha256_hex, utc_text
from weather.schema_families import schema_version

JOURNAL_SCHEMA = schema_version("evidence_journal")
MANIFEST_SCHEMA = schema_version("evidence_segment_manifest")
DAY_SEAL_SCHEMA = schema_version("evidence_day_seal")
ROTATE_BYTES = 100_000_000
DEFAULT_HOUR_BYTE_BUDGET = 8 * 1024**2
MAX_LINE_BYTES = 16 * 1024**2
STATE_LOOKBACK_HOURS = 48
DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
SEGMENT_RE = re.compile(r"\d{2}-[0-9a-f]{12}\Z")
NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
EVENTS, HEARTBEAT, ROWS = "events", "heartbeat", "rows"


class JournalBusy(RuntimeError):
    """Another process holds this family's writer lock."""


class WriterLock:
    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise JournalBusy(f"{self.path} is held by another writer") from None
        self.handle = handle
        return self

    def release(self):
        if self.handle is not None:
            self.handle.close()
            self.handle = None


def atomic_bytes(path, raw: bytes) -> None:
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def file_sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def gzip_content_sha256(path) -> str:
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _plain_stats(path) -> dict:
    digest, size, records, last = hashlib.sha256(), 0, 0, b""
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
            size += len(block)
            records += block.count(b"\n")
            last = block[-1:]
    return {"sha256": digest.hexdigest(), "bytes": size, "records": records,
            "torn_tail": bool(size) and last != b"\n"}


def segment_dirs(day_dir) -> list[Path]:
    day_dir = Path(day_dir)
    if not day_dir.is_dir():
        return []
    return sorted(p for p in day_dir.iterdir() if p.is_dir() and SEGMENT_RE.match(p.name))


def day_dirs(family_root) -> list[Path]:
    family_root = Path(family_root)
    if not family_root.is_dir():
        return []
    return sorted(p for p in family_root.iterdir() if p.is_dir() and DAY_RE.match(p.name))


def segment_files(segment) -> list[tuple[str, Path, bool]]:
    """``(partition file name, path, compressed)`` for one segment, sealed or open."""
    segment = Path(segment)
    manifest = segment / "manifest.json"
    if manifest.exists():
        import json
        info = json.loads(manifest.read_bytes())
        out = []
        for name in sorted(info["files"]):
            gz = segment / (name + ".gz")
            out.append((name, gz, True) if gz.exists() else (name, segment / name, False))
        return out
    return [(p.name, p, False) for p in sorted(segment.glob("*.jsonl"))]


def iter_segment_rows(segment, *, partitions=None):
    """Yield ``(partition file name, row)``; a torn or undecodable trailing line is skipped."""
    import json
    for name, path, compressed in segment_files(segment):
        if partitions is not None and name.removesuffix(".jsonl") not in partitions:
            continue
        opener = gzip.open if compressed else open
        with opener(path, "rb") as handle:
            while line := handle.readline(MAX_LINE_BYTES + 1):
                if not line.endswith(b"\n"):
                    break
                try:
                    yield name, json.loads(line)
                except ValueError:
                    break


class EvidenceJournal:
    def __init__(self, root, family, *, clock=None, rotate_bytes=ROTATE_BYTES,
                 hour_byte_budget=DEFAULT_HOUR_BYTE_BUDGET, config_sha256="", code_manifest_sha="",
                 on_day_seal=None, state_lookback_hours=STATE_LOOKBACK_HOURS):
        if not NAME_RE.match(family):
            raise ValueError("invalid family id")
        self.root = Path(root)
        self.family = family
        self.family_root = self.root / family
        self.cas_root = self.root / "cas" / "sha256"
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.rotate_bytes, self.hour_byte_budget = int(rotate_bytes), int(hour_byte_budget)
        self.config_sha256, self.code_manifest_sha = config_sha256, code_manifest_sha
        self.on_day_seal = on_day_seal
        self.state_lookback_hours = state_lookback_hours
        self.lock = WriterLock(self.family_root / ".writer.lock")
        self.day = self.hour = ""
        self.folder = None
        self.files: dict[str, dict] = {}
        self.segment_bytes = self.hour_bytes = 0
        self.hour_capped = False
        self.latest: dict[tuple[str, str], str] = {}
        self.counters = {"bytes_appended": 0, "rows": 0, "heartbeats": 0, "events": 0, "dropped_rows": 0,
                         "segments_sealed": 0, "days_sealed": 0, "cas_objects": 0, "cas_bytes": 0, "caps": 0}
        self.cap_hit_hours: list[str] = []
        self.opened = False

    # lifecycle -------------------------------------------------------------------------------
    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    def open(self):
        self.lock.acquire()
        try:
            self._recover()
            self._rebuild_latest()
        except BaseException:
            self.lock.release()
            raise
        self.opened = True
        return self

    def close(self):
        if not self.opened:
            return
        try:
            self._seal_segment()
        finally:
            self.lock.release()
            self.opened = False

    # recovery --------------------------------------------------------------------------------
    def _recover(self):
        for day_dir in day_dirs(self.family_root):
            for segment in segment_dirs(day_dir):
                manifest = segment / "manifest.json"
                if manifest.exists():
                    self._finish_cleanup(segment)
                else:
                    self._seal_folder(segment)
        today = self.clock().astimezone(timezone.utc).date().isoformat()
        for day_dir in day_dirs(self.family_root):
            if day_dir.name < today:
                self._seal_day(day_dir.name)

    def _finish_cleanup(self, segment):
        import json
        info = json.loads((segment / "manifest.json").read_bytes())
        for name, entry in info["files"].items():
            plain, gz = segment / name, segment / (name + ".gz")
            if plain.exists() and gz.exists() and gzip_content_sha256(gz) == entry["sha256"]:
                plain.unlink()

    def _rebuild_latest(self):
        now = self.clock().astimezone(timezone.utc)
        horizon = now.timestamp() - self.state_lookback_hours * 3600
        for day_dir in day_dirs(self.family_root):
            day_end = datetime.fromisoformat(day_dir.name).replace(tzinfo=timezone.utc).timestamp() + 86400
            if day_end < horizon:
                continue
            for segment in segment_dirs(day_dir):
                for _, row in iter_segment_rows(segment, partitions=None):
                    if row.get("kind") == "row" and row.get("channel") and row.get("key") is not None:
                        self.latest[(row["channel"], str(row["key"]))] = row["content_sha256"]

    # sealing ---------------------------------------------------------------------------------
    def _seal_folder(self, folder) -> dict:
        folder = Path(folder)
        for stale in folder.glob("*.gz.tmp"):
            stale.unlink()
        files = {}
        for plain in sorted(folder.glob("*.jsonl")):
            stats = _plain_stats(plain)
            gz = folder / (plain.name + ".gz")
            temporary = folder / (plain.name + ".gz.tmp")
            with plain.open("rb") as source, gzip.open(temporary, "wb", compresslevel=6) as target:
                shutil.copyfileobj(source, target, 1 << 20)
            if gzip_content_sha256(temporary) != stats["sha256"]:
                temporary.unlink()
                raise OSError(f"gzip verification failed for {plain}")
            os.replace(temporary, gz)
            files[plain.name] = {**stats, "gz_sha256": file_sha256(gz), "gz_bytes": gz.stat().st_size}
        info = {"schema_version": MANIFEST_SCHEMA, "family": self.family, "day": folder.parent.name,
                "segment": folder.name, "sealed_at_utc": utc_text(self.clock()), "files": files}
        atomic_bytes(folder / "manifest.json", canonical(info) + b"\n")
        for name in files:
            (folder / name).unlink()
        self.counters["segments_sealed"] += 1
        return info

    def _seal_segment(self):
        if self.folder is None:
            return None
        info = self._seal_folder(self.folder)
        self.folder, self.files, self.segment_bytes = None, {}, 0
        return info

    def _previous_seal(self, day):
        for day_dir in reversed(day_dirs(self.family_root)):
            if day_dir.name < day and (day_dir / "day_seal.json").exists():
                return day_dir.name, file_sha256(day_dir / "day_seal.json")
        return None, None

    def _seal_day(self, day):
        day_dir = self.family_root / day
        seal_path = day_dir / "day_seal.json"
        if seal_path.exists() or not day_dir.is_dir():
            return None
        segments = []
        for segment in segment_dirs(day_dir):
            if not (segment / "manifest.json").exists():
                self._seal_folder(segment)
            segments.append({"segment": segment.name,
                             "manifest_sha256": file_sha256(segment / "manifest.json")})
        prev_day, prev_sha = self._previous_seal(day)
        payload = {"schema_version": DAY_SEAL_SCHEMA, "family": self.family, "day": day,
                   "segments": segments, "prev_day": prev_day, "prev_seal_sha256": prev_sha,
                   "sealed_at_utc": utc_text(self.clock())}
        atomic_bytes(seal_path, canonical(payload) + b"\n")
        self.counters["days_sealed"] += 1
        if self.on_day_seal is not None:
            self.on_day_seal(day, payload)
        return payload

    # writing ---------------------------------------------------------------------------------
    def tick(self):
        """Roll on the clock even when idle: seal a finished hour, seal a finished day."""
        now = self.clock().astimezone(timezone.utc)
        day, hour = now.date().isoformat(), now.strftime("%H")
        if self.day and (day, hour) < (self.day, self.hour):
            raise RuntimeError("UTC clock moved backwards across a journal boundary")
        if (day, hour) == (self.day, self.hour):
            return
        self._seal_segment()
        if self.day and day != self.day:
            self._seal_day(self.day)
        self.day, self.hour = day, hour
        self.hour_bytes, self.hour_capped = 0, False

    def _segment(self):
        self.tick()
        if self.folder is not None and self.segment_bytes >= self.rotate_bytes:
            self._seal_segment()
        if self.folder is None:
            self.folder = self.family_root / self.day / f"{self.hour}-{uuid4().hex[:12]}"
            self.folder.mkdir(parents=True)
            self.files, self.segment_bytes = {}, 0
        return self.folder

    def _append(self, partition, row) -> int:
        if not NAME_RE.match(partition):
            raise ValueError("invalid partition name")
        folder = self._segment()
        name = partition + ".jsonl"
        offset = self.files.get(name, 0)
        raw = canonical({**row, "offset": offset}) + b"\n"
        if len(raw) > MAX_LINE_BYTES:
            raise ValueError("journal row exceeds MAX_LINE_BYTES")
        with (folder / name).open("ab") as handle:
            if handle.tell() != offset:
                raise OSError("journal file changed outside the writer")
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        self.files[name] = offset + len(raw)
        self.segment_bytes += len(raw)
        self.hour_bytes += len(raw)
        self.counters["bytes_appended"] += len(raw)
        return offset

    def _base(self, kind, channel, captured):
        return {"schema_version": JOURNAL_SCHEMA, "kind": kind, "family": self.family, "channel": channel,
                "captured_at_utc": captured}

    def _within_budget(self, size, channel) -> bool:
        if self.hour_capped:
            return False
        if self.hour_bytes + size <= self.hour_byte_budget:
            return True
        self.hour_capped = True
        self.counters["caps"] += 1
        self.cap_hit_hours.append(f"{self.day}T{self.hour}")
        self.event("cap", {"reason": "hour_byte_budget", "limit_bytes": self.hour_byte_budget,
                           "hour_bytes": self.hour_bytes}, channel=channel)
        return False

    def record_poll(self, channel, items, *, captured_at=None, meta=None, partition=ROWS) -> dict:
        """Write changed items as rows plus one heartbeat row for the poll; return the summary."""
        if not NAME_RE.match(channel):
            raise ValueError("invalid channel name")
        self.tick()
        captured = utc_text(captured_at or self.clock())
        pairs, changed, unchanged, dropped = [], 0, 0, 0
        for item in items:
            key, body = str(item["key"]), item["body"]
            content = sha256_hex(canonical(body))
            pairs.append([key, content])
            if self.latest.get((channel, key)) == content:
                unchanged += 1
                continue
            row = {**self._base("row", channel, captured), "key": key, "content_sha256": content,
                   "first_seen_utc": captured, **item["envelope"], **(item.get("meta") or {}),
                   "config_sha256": self.config_sha256, "code_manifest_sha": self.code_manifest_sha,
                   "body": body}
            if not self._within_budget(len(canonical(row)) + 32, channel):
                dropped += 1
                continue
            self._append(item.get("partition") or partition, row)
            self.latest[(channel, key)] = content
            changed += 1
        pairs.sort()
        heartbeat = {**self._base("heartbeat", channel, captured), "capture_id": uuid4().hex,
                     "batch_hash": sha256_hex(canonical(pairs)), "items": len(pairs), "changed": changed,
                     "unchanged": unchanged, "dropped": dropped, **(meta or {})}
        self._append(HEARTBEAT, heartbeat)
        self.counters["rows"] += changed
        self.counters["heartbeats"] += 1
        self.counters["dropped_rows"] += dropped
        return {"changed": changed, "unchanged": unchanged, "dropped": dropped, "items": len(pairs),
                "batch_hash": heartbeat["batch_hash"]}

    def event(self, kind, payload, *, channel=None, captured_at=None) -> int:
        """gap, cap, guard, warn, pause, resume, identity, start or stop row (always written)."""
        self.tick()
        row = {**self._base(kind, channel, utc_text(captured_at or self.clock())), **payload}
        self.counters["events"] += 1
        return self._append(EVENTS, row)

    def seen(self, channel, key) -> bool:
        return (channel, str(key)) in self.latest

    def put_raw(self, raw: bytes, *, channel=None) -> str | None:
        """Store raw bytes once in the CAS; None when the hour's byte budget is spent."""
        digest = sha256_hex(raw)
        path = self.cas_root / digest[:2] / f"{digest}.blob"
        if path.exists():
            return "sha256:" + digest
        self.tick()
        if not self._within_budget(len(raw), channel):
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_bytes(path, raw)
        self.hour_bytes += len(raw)
        self.counters["cas_objects"] += 1
        self.counters["cas_bytes"] += len(raw)
        self.counters["bytes_appended"] += len(raw)
        return "sha256:" + digest


def read_raw(root, raw_ref: str) -> bytes:
    algorithm, _, digest = str(raw_ref).partition(":")
    if algorithm != "sha256" or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid raw_ref")
    raw = (Path(root) / "cas" / "sha256" / digest[:2] / f"{digest}.blob").read_bytes()
    if sha256_hex(raw) != digest:
        raise OSError("CAS object does not match its name")
    return raw


def verify_seal_chain(family_root, *, deep=False) -> dict:
    """Walk the day seals in order: each points at the previous seal and at intact manifests."""
    import json
    problems, days, prev_day, prev_sha = [], [], None, None
    for day_dir in day_dirs(family_root):
        seal_path = day_dir / "day_seal.json"
        if not seal_path.exists():
            continue
        seal = json.loads(seal_path.read_bytes())
        days.append(day_dir.name)
        if seal.get("prev_day") != prev_day or seal.get("prev_seal_sha256") != prev_sha:
            problems.append(f"{day_dir.name}: chain pointer does not match the previous seal")
        for entry in seal.get("segments", []):
            manifest = day_dir / entry["segment"] / "manifest.json"
            if not manifest.exists() or file_sha256(manifest) != entry["manifest_sha256"]:
                problems.append(f"{day_dir.name}/{entry['segment']}: manifest missing or changed")
                continue
            if deep:
                info = json.loads(manifest.read_bytes())
                for name, stats in info["files"].items():
                    gz = manifest.parent / (name + ".gz")
                    if not gz.exists() or gzip_content_sha256(gz) != stats["sha256"]:
                        problems.append(f"{day_dir.name}/{entry['segment']}/{name}: content changed")
        prev_day, prev_sha = day_dir.name, file_sha256(seal_path)
    return {"ok": not problems, "days": days, "problems": problems}
