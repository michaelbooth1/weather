"""Stream sealed 88a reward journals into the frozen 89a terms contract.

Planning reads directory metadata only. Reading verifies the store's manifest,
uncompressed offsets and payload hashes; no active segment or daily load.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from weather.market.fill_toxicity_inputs import MAX_LINE_BYTES, epoch, term_rows
from weather.market.fill_toxicity_model import StudyError
from weather.market.maker_evidence_store import SCHEMA, digest, encoded, MAX_RAW_BYTES


REWARD_FILE = re.compile(r"reward-[0-9a-f]{24}\.jsonl(?:\.gz)?")
SEGMENT = re.compile(r"(\d{2})-[0-9a-f]{12}")
MAX_FILES = 20000
MAX_MANIFEST_BYTES = 2 * 1024**2


def manifest_path(folder):
    for name in ("manifest.json.gz", "manifest.json"):
        path = folder / name
        if path.is_file():
            return path
    return None


def plan_rewards(root, start, end):
    """Only overlapping UTC hours, including the existing one-hour lookback."""
    first = datetime.fromtimestamp(start - 3600, timezone.utc)
    last = datetime.fromtimestamp(end - 0.000001, timezone.utc)
    paths = []
    day = first.date()
    while day <= last.date():
        folder = Path(root) / day.isoformat()
        if folder.is_dir():
            for segment in folder.iterdir():
                match = SEGMENT.fullmatch(segment.name)
                if not match or not segment.is_dir() or int(match[1]) > 23:
                    continue
                hour = datetime.combine(day, datetime.min.time(), timezone.utc).timestamp() + int(match[1]) * 3600
                if hour >= end or hour + 3600 <= start - 3600 or manifest_path(segment) is None:
                    continue
                for path in segment.glob("reward-*.jsonl.gz"):
                    if REWARD_FILE.fullmatch(path.name) and path.is_file():
                        paths.append(str(path))
                        if len(paths) > MAX_FILES:
                            raise StudyError("maker reward input file budget exceeded")
        day += timedelta(days=1)
    return sorted(paths)


def _json(raw, path):
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise StudyError(f"undecodable unlocatable maker reward record: {path}") from None
    if not isinstance(value, dict):
        raise StudyError(f"expected maker reward object: {path}")
    return value


def _manifest(path):
    seal = manifest_path(path.parent)
    if seal is None:
        raise StudyError(f"unsealed maker reward segment: {path.parent}")
    with (gzip.open if seal.suffix == ".gz" else open)(seal, "rb") as handle:
        raw = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise StudyError("maker reward manifest exceeds byte budget")
    info = _json(raw, seal)
    files = info.get("files")
    if info.get("schema_version") != SCHEMA or epoch(info.get("sealed_at_utc")) is None or not isinstance(files, dict):
        raise StudyError(f"invalid sealed maker reward manifest: {seal}")
    if len(files) > MAX_FILES:
        raise StudyError("maker reward manifest exceeds file budget")
    for name, expected in files.items():
        if (not isinstance(expected, dict) or type(expected.get("bytes")) is not int
                or not 0 <= expected["bytes"] <= MAX_RAW_BYTES):
            raise StudyError(f"invalid maker reward file size: {name}")
    return files


def _record(handle, path):
    offset = handle.tell()
    raw = handle.readline(MAX_LINE_BYTES + 1)
    if not raw:
        return None, raw
    if len(raw) > MAX_LINE_BYTES or not raw.endswith(b"\n"):
        raise StudyError(f"oversized or torn maker reward record: {path}")
    row = _json(raw, path)
    if row.get("offset") != offset:
        raise StudyError(f"maker reward offset mismatch: {path}")
    return row, raw


def reward_rows(path, event_slug, start, end):
    """Reuse a stored body, never its timestamp, for an unchanged minute.

88a points directly to a body-stored row in the same segment. Retain only the
last body; older/cross-file references use bounded gzip seeks, not a day cache.
Shared undecodable evidence cannot be located to a market-date, so it refuses
under Clarification 9 rather than silently losing coverage.
"""
    path = Path(path)
    files = _manifest(path)
    name = path.name.removesuffix(".gz")
    if not REWARD_FILE.fullmatch(path.name) or name not in files:
        raise StudyError(f"maker reward file absent from seal: {path}")
    expected = files[name]
    hashed, count, size, cached = hashlib.sha256(), 0, 0, None
    with gzip.open(path, "rb") as handle:
        while True:
            row, raw = _record(handle, path)
            if row is None:
                break
            hashed.update(raw)
            count += 1
            size += len(raw)
            if size > expected["bytes"]:
                raise StudyError(f"maker reward stream exceeds sealed size: {path}")
            at = epoch(row.get("captured_at_utc"))
            if row.get("kind") != "rewards" or at is None:
                raise StudyError(f"invalid maker reward kind/capture time: {path}")
            stored = row
            if row.get("body_stored") is False:
                ref = row.get("payload_ref")
                if (not isinstance(ref, dict) or not isinstance(ref.get("file"), str)
                        or not re.fullmatch(r"reward-[0-9a-f]{24}\.jsonl", ref["file"])
                        or ref["file"] not in files or type(ref.get("offset")) is not int
                        or not 0 <= ref["offset"] < files[ref["file"]]["bytes"]):
                    raise StudyError(f"invalid maker reward payload reference: {path}")
                if cached and (ref["file"], ref["offset"]) == cached[:2]:
                    stored = cached[2]
                else:
                    target = path.parent / (ref["file"] + ".gz")
                    with gzip.open(target, "rb") as source:
                        source.seek(ref["offset"])
                        stored, _ = _record(source, target)
                if (not stored or stored.get("body_stored") is not True
                        or stored.get("change_key") != row.get("change_key")
                        or stored.get("url") != row.get("url")
                        or epoch(stored.get("captured_at_utc")) is None
                        or epoch(stored["captured_at_utc"]) > at
                        or stored.get("content_sha256") != row.get("content_sha256")):
                    raise StudyError(f"maker reward payload reference mismatch: {path}")
            elif row.get("body_stored") is not True:
                raise StudyError(f"maker reward body storage flag missing: {path}")
            if not isinstance(stored.get("body_utf8"), str):
                raise StudyError(f"maker reward UTF-8 body missing: {path}")
            body = _json(stored["body_utf8"], path)
            if digest(encoded(body)) != row.get("content_sha256"):
                raise StudyError(f"maker reward content hash mismatch: {path}")
            if row["body_stored"]:
                cached = (name, row["offset"], row)
            if not start - 3600 <= at < end:
                continue
            if row.get("http_status") != 200 or not isinstance(body.get("data"), list):
                raise StudyError(f"invalid maker reward response: {path}")
            url = urlsplit(str(row.get("url", "")))
            condition = url.path.removeprefix("/rewards/markets/")
            if (url.scheme != "https" or url.netloc != "clob.polymarket.com" or url.fragment
                    or not url.path.startswith("/rewards/markets/")
                    or not re.fullmatch(r"0x[0-9a-fA-F]{64}", condition)):
                raise StudyError(f"invalid maker reward condition URL: {path}")
            for item in body["data"]:
                if not isinstance(item, dict) or str(item.get("condition_id", "")).lower() != condition.lower():
                    raise StudyError(f"maker reward condition mismatch: {path}")
                if item.get("event_slug") == event_slug:
                    # Outer capture time is authoritative even if an inner field exists.
                    yield {**item, "captured_at_utc": row["captured_at_utc"]}
    if (size != expected["bytes"] or count != expected.get("records")
            or hashed.hexdigest() != expected.get("sha256")):
        raise StudyError(f"maker reward sealed file integrity mismatch: {path}")


def stage_rewards(db, paths, event_slug, start, end):
    for path in paths:
        for row in reward_rows(path, event_slug, start, end):
            for terms in term_rows(row):
                db.execute("INSERT INTO terms VALUES (?,?,?,?,?,?,?)", terms)
    db.commit()
