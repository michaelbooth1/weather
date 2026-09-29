"""Bounded, read-only inputs for the competitor-reaction diagnostic (mission 111f).

Every reader here takes an explicit UTC date allow-list and refuses any date in
the maker-replay quote panel (2026-09-30..2026-10-14). Caps match the weather
maker plugin's capture reader: 64 MiB per file (decompressed), 1 MiB per line,
100,000 rows per file, 1 GiB of input per run and a wall-clock limit. Nothing
is written, renamed or deleted; unsealed 88a segments are never opened.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import time

PANEL_FIRST = date(2026, 9, 30)
PANEL_LAST = date(2026, 10, 14)
CALIBRATION_DATES = ("2026-09-27", "2026-09-28", "2026-09-29")
MAX_FILE_BYTES = 64 * 1024**2
MAX_LINE_BYTES = 1024**2
MAX_ROWS = 100_000
MAX_INPUT_BYTES = 1024**3
MAX_SECONDS = 2700
MAX_SEGMENTS_PER_DAY = 2000
MAX_MANIFEST_BYTES = 2 * 1024**2
SEGMENT_NAME = re.compile(r"\d{2}-[0-9a-f]{12}")
CONDITION = re.compile(r"0x[0-9a-f]{64}")
TOKEN = re.compile(r"[0-9]{1,100}")
TRIGGER_DATE = re.compile(rb'"current_captured_at_utc":\s*"(\d{4}-\d{2}-\d{2})T')
BAND_FIELDS = ("event_slug", "captured_at_utc", "condition_id", "bin_kind", "bin_value_c", "bin_value_hi_c")


class StopRun(RuntimeError):
    """A run-wide bound was reached; the run refuses rather than truncating silently."""


class InputRefused(ValueError):
    """One input file violated a bound or an integrity check."""


def parse_utc(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp_not_timezone_aware")
    return result.astimezone(timezone.utc)


def allow_list(values, *, calibration_only=False):
    """Validate an explicit UTC date allow-list; refuse every quote-panel date."""
    days = sorted({date.fromisoformat(str(value).strip()) for value in values if str(value).strip()})
    if not days:
        raise ValueError("date allow-list is empty")
    panel = [d.isoformat() for d in days if PANEL_FIRST <= d <= PANEL_LAST]
    if panel:
        raise ValueError("refused quote-panel date(s): " + ", ".join(panel))
    if calibration_only and any(d.isoformat() not in CALIBRATION_DATES for d in days):
        raise ValueError("latency reads calibration dates 2026-09-27..2026-09-29 only")
    return tuple(d.isoformat() for d in days)


class Budget:
    """Run-wide byte and time budget shared by every reader."""

    def __init__(self, max_input_bytes=MAX_INPUT_BYTES, max_seconds=MAX_SECONDS, clock=time.monotonic):
        if not 0 < max_input_bytes <= MAX_INPUT_BYTES or not 0 < max_seconds <= MAX_SECONDS:
            raise ValueError("budget exceeds plugin caps")
        self.max_input_bytes, self.max_seconds, self.clock = max_input_bytes, max_seconds, clock
        self.started = clock()
        self.bytes = 0
        self.coverage = Counter()

    def charge(self, amount):
        self.bytes += amount
        if self.bytes > self.max_input_bytes:
            raise StopRun("input_byte_cap")
        if self.clock() - self.started > self.max_seconds:
            raise StopRun("time_cap")


def variant(path):
    """Prefer the plain file; accept the sealed ``.gz`` sibling."""
    path = Path(path)
    if path.is_file():
        return path
    zipped = path.with_name(path.name + ".gz")
    return zipped if zipped.is_file() else path


def iter_lines(path, budget, *, max_file_bytes=MAX_FILE_BYTES, max_rows=MAX_ROWS, sha=None):
    """Yield raw lines (decompressed) under the per-file, per-line and run caps."""
    path = Path(path)
    if path.is_symlink():
        raise InputRefused("symlink_refused")
    opener = gzip.open if path.suffix == ".gz" else open
    total = rows = 0
    with opener(path, "rb") as handle:
        while line := handle.readline(MAX_LINE_BYTES + 1):
            if len(line) > MAX_LINE_BYTES:
                raise InputRefused("line_byte_cap")
            total += len(line)
            rows += 1
            if total > max_file_bytes:
                raise InputRefused("file_byte_cap")
            if rows > max_rows:
                raise InputRefused("file_row_cap")
            budget.charge(len(line))
            if sha is not None:
                sha.update(line)
            yield line


# --------------------------------------------------------------------------
# 88a sealed segments
# --------------------------------------------------------------------------

def decode_body(row):
    if "body_utf8" in row:
        return row["body_utf8"]
    raise InputRefused("unsupported_inline_body")


class Segment:
    def __init__(self, folder, files):
        self.folder, self.files = folder, files

    def path(self, name):
        if name not in self.files or Path(name).name != name:
            raise InputRefused("undeclared_journal_file")
        return variant(self.folder / name)

    def rows(self, name, budget):
        """Parsed rows of one declared file, verified against the sealed manifest."""
        expected = self.files[name]
        sha = hashlib.sha256()
        offset = 0
        for line in iter_lines(self.path(name), budget, sha=sha):
            row = json.loads(line)
            if row.get("offset") != offset:
                raise InputRefused("record_offset_mismatch")
            offset += len(line)
            yield row
        if (sha.hexdigest(), offset) != (expected.get("sha256"), expected.get("bytes")):
            raise InputRefused("sealed_file_integrity_mismatch")


def sealed_segments(root, day, budget):
    """Sealed 88a segments of one allowed UTC date, in folder order."""
    folder = Path(root) / day
    if not folder.is_dir():
        budget.coverage["books.days_missing"] += 1
        return []
    result = []
    for child in sorted(folder.iterdir()):
        if not child.is_dir() or not SEGMENT_NAME.fullmatch(child.name):
            continue
        manifest = variant(child / "manifest.json")
        if not manifest.is_file():
            budget.coverage["books.unsealed_segments_skipped"] += 1
            continue
        with (gzip.open if manifest.suffix == ".gz" else open)(manifest, "rb") as handle:
            raw = handle.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise InputRefused("oversized_segment_manifest")
        budget.charge(len(raw))
        info = json.loads(raw)
        if not isinstance(info.get("files"), dict):
            raise InputRefused("invalid_segment_manifest")
        result.append(Segment(child, info["files"]))
        if len(result) > MAX_SEGMENTS_PER_DAY:
            raise InputRefused("segment_count_cap")
    budget.coverage["books.sealed_segments"] += len(result)
    return result


def read_universe(root, days, budget):
    """condition_id -> {city, event_slug, yes_token, no_token} from 88a universe events."""
    bands = {}
    for day in days:
        for segment in sealed_segments(root, day, budget):
            for name in sorted(segment.files):
                if not name.startswith("universe-"):
                    continue
                for row in segment.rows(name, budget):
                    if row.get("kind") != "universe" or "body_utf8" not in row:
                        continue
                    for band in json.loads(row["body_utf8"]).get("bands", []):
                        cid = str(band.get("condition_id", "")).lower()
                        tokens = [str(t) for t in band.get("tokens") or []]
                        if CONDITION.fullmatch(cid) and len(tokens) == 2:
                            bands[cid] = {"city": band.get("city"), "event_slug": band.get("event_slug"),
                                          "yes_token": tokens[0], "no_token": tokens[1]}
    return bands


def read_books(root, days, tokens, budget):
    """token -> sorted [(captured_at_utc, book_dict)] from sealed 88a book batches.

    Reads ``book-<token>.jsonl`` constituents only for the wanted tokens and
    joins them to the batch records (``books`` and ``ranking_books``) that
    carry the capture clock. Inline (unsplit) batch bodies are parsed whole.
    """
    wanted = {str(t) for t in tokens if TOKEN.fullmatch(str(t))}
    series = {token: [] for token in wanted}
    if not wanted:
        return series
    for day in days:
        for segment in sealed_segments(root, day, budget):
            bodies = {}
            for token in sorted(wanted):
                name = "book-" + token + ".jsonl"
                if name in segment.files:
                    bodies[name] = {row["offset"]: row["body_utf8"] for row in segment.rows(name, budget)
                                    if "body_utf8" in row}
            for kind in ("books", "ranking_books"):
                name = kind + ".jsonl"
                if name not in segment.files:
                    continue
                for row in segment.rows(name, budget):
                    if row.get("kind") != kind:
                        continue
                    when = parse_utc(row["captured_at_utc"])
                    if when.date().isoformat() not in days:
                        continue
                    if "parts" in row:
                        for part in row["parts"]:
                            table = bodies.get(part.get("file"))
                            if table is None or part.get("offset") not in table:
                                continue
                            book = json.loads(table[part["offset"]])
                            if str(book.get("asset_id")) in wanted:
                                series[str(book["asset_id"])].append((when, book))
                    elif "body_utf8" in row:
                        for book in json.loads(row["body_utf8"]) or []:
                            if isinstance(book, dict) and str(book.get("asset_id")) in wanted:
                                series[str(book["asset_id"])].append((when, book))
    for token in series:
        series[token].sort(key=lambda item: item[0])
        budget.coverage["books.token_samples"] += len(series[token])
    return series


# --------------------------------------------------------------------------
# RE-1 attended-session journals
# --------------------------------------------------------------------------

def canonical_line(row):
    return (json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str) + "\n").encode()


def read_journal(path, budget):
    """Rows of one RE-1 ``journal.jsonl`` after the canonical hash-chain check."""
    rows, previous = [], None
    sha = hashlib.sha256()
    for index, line in enumerate(iter_lines(path, budget, sha=sha)):
        row = json.loads(line)
        if (canonical_line(row) != line or row.get("kind") != "journal" or row.get("sequence") != index
                or row.get("previous_sha256") != previous):
            raise InputRefused("journal_chain_broken")
        previous = hashlib.sha256(line).hexdigest()
        rows.append(row)
    return rows, sha.hexdigest()


def session_folders(root):
    root = Path(root)
    if not root.is_dir():
        raise InputRefused("re1_root_missing")
    folders = sorted((p for p in root.iterdir() if p.is_dir() and re.fullmatch(r"session-\d+", p.name)),
                     key=lambda p: int(p.name.split("-")[1]))
    if not 1 <= len(folders) <= 100:
        raise InputRefused("re1_session_count_out_of_bounds")
    return folders


def read_prediction_hash(folder, budget):
    path = Path(folder) / "prediction.json"
    if not path.is_file():
        return None
    raw = b"".join(iter_lines(path, budget))
    return json.loads(raw).get("journal_sha256")


# --------------------------------------------------------------------------
# Observation triggers and band definitions
# --------------------------------------------------------------------------

def read_triggers(paths, days, budget):
    """``wu_history_high_increased`` triggers captured on allowed UTC dates.

    Lines whose trigger capture date is not allowed are discarded from the raw
    bytes before JSON parsing, so no other date's content is decoded.
    """
    found, seen = [], set()
    allowed = {d.encode() for d in days}
    for path in paths:
        path = Path(path)
        if not path.is_file():
            budget.coverage["triggers.files_missing"] += 1
            continue
        for line in iter_lines(path, budget):
            dates = set(TRIGGER_DATE.findall(line))
            if not dates or not dates & allowed:
                budget.coverage["triggers.lines_outside_allow_list"] += 1
                continue
            record = json.loads(line)
            context = record.get("trigger_context") or {}
            for trigger in context.get("triggers") or []:
                if not isinstance(trigger, dict) or trigger.get("reason") != "wu_history_high_increased":
                    continue
                when = parse_utc(trigger["current_captured_at_utc"])
                if when.date().isoformat() not in days:
                    continue
                key = (trigger.get("market_id"), trigger.get("target_date"), when.isoformat(),
                       trigger.get("current_value"))
                if key in seen:
                    continue
                seen.add(key)
                found.append({"market_id": trigger.get("market_id"), "event_slug": trigger.get("event_slug"),
                              "target_date": trigger.get("target_date"), "unit": trigger.get("unit"),
                              "previous_value": trigger.get("previous_value"),
                              "current_value": trigger.get("current_value"), "captured_at": when,
                              "triggered_at_utc": record.get("triggered_at_utc")})
    found.sort(key=lambda t: (t["captured_at"], str(t["market_id"])))
    budget.coverage["triggers.kept"] += len(found)
    return found


def in_panel(day):
    try:
        return PANEL_FIRST <= date.fromisoformat(day) <= PANEL_LAST
    except ValueError:
        return True  # an unparseable capture date is treated as possibly in the panel


def read_bands(snapshots_root, slug, budget):
    """condition_id -> static band definition (native units) from the event's snapshot CSV.

    Band bounds do not change by capture; rows captured on a quote-panel date
    are skipped unused. Returns ``(bands, status)``.
    """
    if not re.fullmatch(r"[a-z0-9-]{1,200}", str(slug or "")):
        return {}, "invalid_event_slug"
    path = variant(Path(snapshots_root) / slug / "snapshots_long.csv")
    if not path.is_file():
        return {}, "snapshot_csv_missing"
    bands, status = {}, "ok"
    header = None
    try:
        for line in iter_lines(path, budget):
            text = line.decode("utf-8")
            if header is None:
                header = next(csv.reader(io.StringIO(text)))
                continue
            values = next(csv.reader(io.StringIO(text)), None)
            if not values or len(values) != len(header):
                continue
            row = dict(zip(header, values))
            cid = row.get("condition_id", "").lower()
            if not CONDITION.fullmatch(cid) or in_panel(row.get("captured_at_utc", "")[:10]):
                continue
            bands.setdefault(cid, {k: row.get(k) for k in BAND_FIELDS})
    except InputRefused as exc:
        status = "partial_" + str(exc)
    return bands, status
