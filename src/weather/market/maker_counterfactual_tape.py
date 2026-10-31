"""Counterfactual quote-minute and fill tape from sealed 88a evidence (item 330 build 2 input).

A fresh, read-only night process. It reads sealed ``maker_evidence_v2`` segments
of the 88a passive capture (``weather.market.maker_evidence_store``) and writes,
per UTC day, two zstd Parquet tables of **counterfactual** records:

* ``cf_minutes``: one hypothetical resting maker BUY per captured token per
  exposure minute, quoted at that token's best bid of the snapshot that opens
  the minute (the hazard denominator);
* ``cf_fills``: the first public ``last_trade_price`` print in that minute that
  would have filled the quote under the paper fill rule
  (``maker_core.shadow.paper.crosses``), with the trailing context at the print
  and YES-mid marks at +1, +5 and +30 minutes.

Nothing here is our own fill; it is the input of the COUNTERFACTUAL toxicity
table of item 330 build 2. ``to-jsonl`` converts sealed days into the neutral
JSONL records that build 2's ``maker_core.replay.toxicity.read_records`` reads.

Contract (docs/operations/passive-maker-evidence-capture.md, "Counterfactual fill tape"):

* Date filter first. A day folder's date is parsed from its NAME before the
  folder is listed or anything inside it is opened. Folders dated
  ``RESERVED_FIRST..RESERVED_LAST`` (2026-09-30..2026-10-15) and after
  ``--max-date`` are never listed, stat'ed or opened; a request whose range
  reaches 2026-09-30 is refused. Inside an allowed day, a band whose event date
  is after ``--max-date`` is dropped from the universe before any of its book
  journals is opened, and its prints are counted and discarded.
* Shared reads only. Every input is opened read-only with
  ``FILE_SHARE_READ | WRITE | DELETE``; ``.writer.lock`` and ``status.json`` are
  never opened and no lock is taken. Unsealed segments are counted, not read.
  Every journal read is checked against its segment manifest (decompressed
  bytes and SHA-256); a difference leaves the day unsealed.
* Create-only output outside ``data``. Tables are written as ``*.partial``, read
  back, then renamed onto a name that does not exist. A day is sealed only by
  ``receipts/<day>.json`` (written only when every check matched); an earlier
  attempt's leftover tables are renamed ``*.orphan-<stamp>``, never overwritten
  or deleted. A mismatch is ``receipts/<day>.mismatch-<stamp>.json``.
* Resumable. A sealed day is skipped; ``--max-days`` and ``--deadline`` count and
  gate only new days; never-attempted days run first (newest first).
* ``export --dry-run`` is stat-only: it lists allowed day and segment folders
  and reads directory-entry sizes; it opens no file.
* Point in time (build 2 ``FillContext``, 4ae3602fa). A context uses only prints
  strictly before its instant: a fill's own print, and any print at or after the
  fill instant, never enter its context. A fill's YES book is also strictly
  before the fill; a minute's book is the quote snapshot at the context instant
  (build 2 admits a book at the instant).
* One fill rule per run, recorded in every receipt; a run refuses an output
  directory sealed under the other rule, so each rule has its own backlog.
  Build 2's default fit uses ``strictly_through``; ``at_price`` is its declared
  sensitivity. ``print_side`` is the print's aggressor (taker) side as recorded.
* Per UTC day only. Nothing reads a neighbouring day folder, so a minute that
  would start on the next UTC day, and a mark due after midnight, are omitted
  and counted. Every timestamp in a day's tape is on that UTC day.

The weather context fields (scheduled print, model cycle, decided probability)
and the settlement are left null; the ``station`` column lets a workstation
step fill the scheduled-print clock. This module is not imported by any capture
loop; keep it that way (it must stay roll-free).
"""
from __future__ import annotations

import argparse
from array import array
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import zlib

from maker_core.shadow.paper import FILL_RULES, crosses
from weather.market.execution_tape_markout import market_close_utc, target_date_from_slug
from weather.market.maker_evidence_store import MAX_LINE_BYTES, SCHEMA, decode_body
from weather.market.market_registry import REGISTRY
from weather.paths import data_path

TAPE_NAME = "maker_counterfactual_tape"
TAPE_REVISION = 1
DAY_RECEIPT_NAME = "cf_tape_day_receipt"
RUN_RECEIPT_NAME = "cf_tape_run_receipt"
DRY_RUN_NAME = "cf_tape_dry_run"
ADAPTER_RECEIPT_NAME = "cf_tape_jsonl_receipt"
SETTLEMENT_WITHHELD_REASONS = ("no_settlement_given", "observed_before_fill", "observed_on_or_after_2026_09_30")
RECEIPT_REVISION = 1
BASIS = "counterfactual"

RESERVED_FIRST = date(2026, 9, 30)   # Reserved exam window (build 2 EXAM_EMBARGO); never read.
RESERVED_LAST = date(2026, 10, 15)
MAX_DATE = date(2026, 9, 29)         # Build 2 FIT_LAST_DATE: the tape stops here.

QUOTE_SIZE = 20.0                    # Shares; the 88a ranking quote size.
MARK_HORIZONS = (("1m", 60), ("5m", 300), ("30m", 1800))
MARK_TOLERANCE_S = 120               # Build 2 MARK_TOLERANCE.
BOOK_MAX_AGE_S = 120                 # A YES book older than this is no context book.
SWEEP_WINDOW_S = 60                  # Build 2 TableSpec / toxicity_features defaults.
BURST_WINDOW_S = 1
MAX_MANIFEST_BYTES = 2 * 1024**2
WRITE_BATCH_ROWS = 50_000
# Dry-run output estimate per input byte. NOT MEASURED on real 88a data; a placeholder until a host run's
# receipt supplies the ratio.
OUTPUT_PER_INPUT_BYTE_UNMEASURED = 0.10

US = 1_000_000
MINUTE_US = 60 * US
DAY_US = 86_400 * US
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

DAY_DIR = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
SEGMENT_DIR = re.compile(r"\d{2}-[0-9a-f]{12}\Z")
ASSET_FILE = re.compile(r"book-([0-9]{1,100})\.jsonl\Z")
UNIVERSE_FILE = re.compile(r"universe-[a-zA-Z0-9_-]{1,100}\.jsonl\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
BOOK_JOURNALS = ("books.jsonl", "ranking_books.jsonl")

MINUTES_TABLE = "cf_minutes"
FILLS_TABLE = "cf_fills"


class TapeRefused(ValueError):
    """The request reaches the reserved window, or the output is inside an input tree."""


class JournalMismatch(ValueError):
    """A journal differs from its segment manifest."""


# ---------------------------------------------------------------- dates


def is_reserved(day: date) -> bool:
    return RESERVED_FIRST <= day <= RESERVED_LAST


def day_folder_date(name: str) -> date | None:
    """The canonical UTC date a day folder NAME states, else None. No filesystem access."""

    if not DAY_DIR.fullmatch(name):
        return None
    try:
        day = date.fromisoformat(name)
    except ValueError:
        return None
    return day if day.isoformat() == name else None


def date_allowed(day: date | None, max_date: date, min_date: date | None) -> bool:
    if day is None or is_reserved(day) or day > max_date:
        return False
    return min_date is None or day >= min_date


def check_request(max_date: date, min_date: date | None) -> None:
    if max_date > MAX_DATE or max_date >= RESERVED_FIRST:
        raise TapeRefused(f"refused: --max-date {max_date} is after {MAX_DATE}; the reserved window "
                          f"{RESERVED_FIRST}..{RESERVED_LAST} is never read")
    if min_date is not None and min_date > max_date:
        raise TapeRefused("refused: --min-date is after --max-date")


def check_out_dir(out_dir: Path, root: Path) -> Path:
    out = Path(os.path.abspath(out_dir))
    for guarded in (Path(os.path.abspath(data_path())), Path(os.path.abspath(root))):
        if out == guarded or guarded in out.parents:
            raise TapeRefused(f"refused: --out-dir {out} is inside the read-only input tree {guarded}")
    return out


def to_us(moment: datetime) -> int:
    if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC-aware")
    delta = moment - EPOCH
    return (delta.days * 86_400 + delta.seconds) * US + delta.microseconds


def from_us(value: int) -> datetime:
    return EPOCH + timedelta(microseconds=int(value))


def day_start_us(day: date) -> int:
    return to_us(datetime(day.year, day.month, day.day, tzinfo=timezone.utc))


# ---------------------------------------------------------------- shared reads


def long_path(path: Path) -> str:
    """Return an OS path that opens past MAX_PATH on Windows."""

    text = os.path.abspath(os.fspath(path))
    if os.name == "nt" and not text.startswith("\\\\?\\"):
        if text.startswith("\\\\"):
            return "\\\\?\\UNC\\" + text[2:]
        return "\\\\?\\" + text
    return text


_FILE_SHARE_READ_WRITE_DELETE = 0x1 | 0x2 | 0x4
_FILE_ATTRIBUTE_NORMAL = 0x80


def open_input(path: Path):
    """Open an input read-only (binary) without blocking any writer, renamer or deleter.

    CPython ``open()`` on Windows does not share delete, so a capture writer or
    the archive (which removes a plain journal after gzip) would fail while this
    process holds the file. Inputs are opened with ``FILE_SHARE_READ | WRITE |
    DELETE`` instead. Elsewhere this is plain ``open()``.
    """

    if os.name != "nt":
        return open(long_path(path), "rb")
    import _winapi
    import msvcrt

    handle = _winapi.CreateFile(long_path(path), _winapi.GENERIC_READ, _FILE_SHARE_READ_WRITE_DELETE, 0,
                                _winapi.OPEN_EXISTING, _FILE_ATTRIBUTE_NORMAL, 0)
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except BaseException:
        _winapi.CloseHandle(handle)
        raise
    return os.fdopen(fd, "rb")


def _open_plain_or_gz(segment: Path, name: str):
    """(handle, gzipped) for ``name`` or ``name.gz``; FileNotFoundError when neither exists."""

    for candidate, gz in ((name, False), (name + ".gz", True)):
        try:
            return open_input(segment / candidate), gz
        except FileNotFoundError:
            continue
    raise FileNotFoundError(str(segment / name))


def read_manifest(segment: Path) -> tuple[dict, str] | None:
    """The sealed manifest and its SHA-256, or None for an unsealed segment (listed, nothing opened)."""

    with os.scandir(long_path(segment)) as entries:
        names = {entry.name for entry in entries}
    if "manifest.json" not in names and "manifest.json.gz" not in names:
        return None
    handle, gz = _open_plain_or_gz(segment, "manifest.json")
    with handle:
        if gz:
            with gzip.GzipFile(fileobj=handle, mode="rb") as stream:
                raw = stream.read(MAX_MANIFEST_BYTES + 1)
        else:
            raw = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise JournalMismatch("manifest exceeds its byte bound")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def iter_journal(segment: Path, name: str, expected: dict, stats: Counter):
    """Yield ``(offset, row)`` of one journal, streamed; raise JournalMismatch at the end on any difference.

    The bytes and SHA-256 of the decompressed journal must equal the manifest's.
    A consumer that used rows of a journal that then mismatches leaves its day unsealed.
    """

    handle, gz = _open_plain_or_gz(segment, name)
    digest, offset = hashlib.sha256(), 0
    with handle:
        stream = gzip.GzipFile(fileobj=handle, mode="rb") if gz else handle
        try:
            while line := stream.readline(MAX_LINE_BYTES + 1):
                if len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
                    raise JournalMismatch(f"{name}: torn or oversized record")
                digest.update(line)
                row = json.loads(line)
                if row.get("offset") != offset:
                    raise JournalMismatch(f"{name}: record offset differs from its position")
                yield offset, row
                offset += len(line)
                if offset > expected["bytes"]:
                    raise JournalMismatch(f"{name}: longer than its manifest")
        finally:
            if gz:
                stream.close()
    stats["journals_read"] += 1
    stats["journal_bytes_read"] += offset
    if offset != expected["bytes"] or digest.hexdigest() != expected["sha256"]:
        raise JournalMismatch(f"{name}: differs from its manifest")


# ---------------------------------------------------------------- listing (names first)


def list_days(root: Path, max_date: date, min_date: date | None) -> tuple[list[tuple[date, Path]], Counter]:
    """Allowed day folders, filtered on the folder NAME before anything inside is listed or opened."""

    allowed, skipped = [], Counter()
    with os.scandir(long_path(root)) as entries:
        for entry in entries:
            day = day_folder_date(entry.name)
            if day is None:
                skipped["not_a_day_folder"] += 1
            elif is_reserved(day):
                skipped["reserved_window_never_opened"] += 1
            elif day > max_date:
                skipped["after_max_date_never_opened"] += 1
            elif min_date is not None and day < min_date:
                skipped["before_min_date"] += 1
            elif entry.is_dir():
                allowed.append((day, Path(root) / entry.name))
            else:
                skipped["not_a_directory"] += 1
    return sorted(allowed), skipped


def list_segments(day_dir: Path) -> list[Path]:
    with os.scandir(long_path(day_dir)) as entries:
        return sorted(Path(day_dir) / e.name for e in entries if SEGMENT_DIR.fullmatch(e.name) and e.is_dir())


# ---------------------------------------------------------------- day extraction


@dataclass(frozen=True)
class Band:
    condition_id: str
    market_id: str
    station: str
    event_slug: str
    event_date: date
    yes_token: str
    no_token: str

    def side(self, token: str) -> str:
        return "YES" if token == self.yes_token else "NO"


class _Book:
    """Per-token snapshot columns, compact (int microseconds; NaN for an empty side)."""

    __slots__ = ("times", "bid", "ask", "bid_depth", "ask_depth")

    def __init__(self):
        self.times, self.bid, self.ask = array("q"), array("d"), array("d")
        self.bid_depth, self.ask_depth = array("d"), array("d")

    def add(self, at_us, body):
        bids = [(float(level["price"]), float(level["size"])) for level in body.get("bids") or ()]
        asks = [(float(level["price"]), float(level["size"])) for level in body.get("asks") or ()]
        self.times.append(at_us)
        self.bid.append(max(p for p, _ in bids) if bids else math.nan)
        self.ask.append(min(p for p, _ in asks) if asks else math.nan)
        self.bid_depth.append(sum(s for _, s in bids))
        self.ask_depth.append(sum(s for _, s in asks))

    def sort(self):
        if all(a <= b for a, b in zip(self.times, self.times[1:])):
            return
        order = sorted(range(len(self.times)), key=self.times.__getitem__)
        for name in self.__slots__:
            column = getattr(self, name)
            setattr(self, name, array(column.typecode, (column[i] for i in order)))


class DayData:
    """Everything one UTC day contributes: bands, YES/NO book snapshots, deduplicated prints."""

    def __init__(self, day: date, max_date: date):
        self.day, self.max_date = day, max_date
        self.bands: dict[str, Band] = {}        # token -> band (allowed event dates only)
        self.refused_tokens: set[str] = set()   # tokens of bands dated after max_date
        self.books: dict[str, _Book] = defaultdict(_Book)
        self.prints: dict[str, set] = defaultdict(set)   # token -> {(t_us, price, size, side)}
        self.dispositions = Counter()
        self.stats = Counter()
        self.segments: list[dict] = []
        self.errors: list[str] = []

    # -- universe
    def add_band(self, row: dict) -> None:
        tokens = [str(t) for t in row.get("tokens") or ()]
        event_date = target_date_from_slug(row.get("event_slug") or "")
        spec = REGISTRY.get(str(row.get("city")))
        if len(tokens) != 2 or not row.get("condition_id"):
            self.dispositions["band_malformed"] += 1
            return
        if event_date is None:
            self.dispositions["band_without_event_date"] += 1
            return
        if event_date > self.max_date or is_reserved(event_date):
            self.refused_tokens.update(tokens)
            self.dispositions["band_event_after_max_date"] += 1
            return
        if spec is None:
            self.dispositions["band_unknown_market"] += 1
            return
        band = Band(str(row["condition_id"]).lower(), spec.id, spec.icao, str(row["event_slug"]), event_date,
                    tokens[0], tokens[1])
        for token in tokens:
            prior = self.bands.get(token)
            if prior is not None and prior != band:
                self.dispositions["band_conflicting_mapping"] += 1
                continue
            self.bands[token] = band
        self.dispositions["band_rows"] += 1

    # -- one sealed segment
    def read_segment(self, segment: Path) -> None:
        found = read_manifest(segment)
        if found is None:
            self.segments.append({"segment": segment.name, "sealed": False})
            self.stats["unsealed_segments_skipped"] += 1
            return
        info, manifest_sha = found
        record = {"segment": segment.name, "sealed": True, "manifest_sha256": manifest_sha}
        self.segments.append(record)
        if info.get("schema_version") != SCHEMA:
            raise JournalMismatch(f"{segment.name}: unsupported evidence schema")
        files = info["files"]
        for name in sorted(n for n in files if UNIVERSE_FILE.fullmatch(n)):
            for _, row in iter_journal(segment, name, files[name], self.stats):
                body = json.loads(decode_body(row)) if ("body_utf8" in row or "body_base64" in row) else None
                for band in (body or {}).get("bands") or ():
                    self.add_band(band)
        refs: dict[str, dict[int, int]] = defaultdict(dict)
        for name in BOOK_JOURNALS:
            if name not in files:
                continue
            for _, row in iter_journal(segment, name, files[name], self.stats):
                if "parts" not in row:
                    self.dispositions[f"{name}:row_without_split_books"] += 1
                    continue
                captured = to_us(datetime.fromisoformat(row["captured_at_utc"]))
                for part in row["parts"]:
                    match = ASSET_FILE.fullmatch(str(part.get("file", "")))
                    if not match:
                        continue
                    token = match.group(1)
                    if token in self.bands:
                        refs[part["file"]][int(part["offset"])] = captured
                    elif token in self.refused_tokens:
                        self.dispositions["book_ref_event_after_max_date_not_opened"] += 1
                    else:
                        self.dispositions["book_ref_outside_universe_not_opened"] += 1
        for name in sorted(refs):
            wanted = refs[name]
            if name not in files:
                self.dispositions["book_ref_missing_journal"] += len(wanted)
                continue
            token = ASSET_FILE.fullmatch(name).group(1)
            book = self.books[token]
            for offset, row in iter_journal(segment, name, files[name], self.stats):
                captured = wanted.pop(offset, None)
                if captured is None:
                    continue
                body = json.loads(row["body_utf8"])
                if str(body.get("asset_id")) != token:
                    raise JournalMismatch(f"{name}: book asset differs from its journal")
                book.add(captured, body)
                self.stats["book_snapshots"] += 1
            self.dispositions["book_ref_missing_record"] += len(wanted)
        if "trades.jsonl" in files:
            start, end = day_start_us(self.day), day_start_us(self.day) + DAY_US
            for _, row in iter_journal(segment, "trades.jsonl", files["trades.jsonl"], self.stats):
                if "payload_ref" in row:
                    self.dispositions["trade_row_payload_ref"] += 1
                    continue
                message = json.loads(decode_body(row))
                for event in message if isinstance(message, list) else [message]:
                    if not isinstance(event, dict) or event.get("event_type") != "last_trade_price":
                        continue
                    token = str(event.get("asset_id"))
                    if token in self.refused_tokens:
                        self.dispositions["print_event_after_max_date_discarded"] += 1
                        continue
                    if token not in self.bands:
                        self.dispositions["print_outside_universe"] += 1
                        continue
                    at = int(event["timestamp"]) * 1000
                    if not start <= at < end:
                        self.dispositions["print_outside_utc_day"] += 1
                        continue
                    before = len(self.prints[token])
                    self.prints[token].add((at, float(event["price"]), float(event["size"]),
                                            str(event.get("side", ""))))
                    self.dispositions["print_kept" if len(self.prints[token]) > before
                                      else "print_duplicate_collapsed"] += 1
        self.stats["segments_read"] += 1


class _EventPrints:
    """Time-ordered prints of every band of one event: (t_us, condition_id, size)."""

    def __init__(self, rows):
        self.rows = sorted(rows)
        self.times = [r[0] for r in self.rows]

    def window(self, start_us, end_us):
        """Prints in ``[start_us, end_us)``: strictly before the context instant."""
        return self.rows[bisect_left(self.times, start_us):bisect_left(self.times, end_us)]


def _context(day: DayData, band: Band, side: str, at_us: int, event_prints: _EventPrints, *,
             book_strict: bool = False) -> dict | None:
    """Build 2 ``FillContext`` fields at ``at_us`` from trailing data only; None if the band is closed.

    Prints are strictly before ``at_us`` (the print at a fill instant is the fill itself). ``book_strict``
    (fills) takes the YES book strictly before ``at_us`` too; a minute uses its quote snapshot at ``at_us``.
    """

    spec = REGISTRY[band.market_id]
    at = from_us(at_us)
    horizon = (band.event_date - at.astimezone(spec.tz).date()).days
    close, _ = market_close_utc(band.market_id, band.event_date)
    to_close = (close - at).total_seconds() / 60
    if horizon < 0 or to_close < 0:
        return None
    yes = day.books.get(band.yes_token)
    imbalance, depth, book_at = None, 0.0, None
    if yes is not None:
        index = (bisect_left(yes.times, at_us) if book_strict else bisect_right(yes.times, at_us)) - 1
        if index >= 0 and at_us - yes.times[index] <= BOOK_MAX_AGE_S * US:
            bid, ask = yes.bid_depth[index], yes.ask_depth[index]
            depth = bid + ask
            imbalance = (bid - ask) / depth if depth else None
            book_at = yes.times[index]
    recent = event_prints.window(at_us - SWEEP_WINDOW_S * US, at_us)
    own = [(t, size) for t, condition, size in recent if condition == band.condition_id]
    return {
        "ctx_at_utc": at_us, "ctx_horizon_days": horizon, "ctx_minutes_to_close": to_close,
        "ctx_minutes_from_scheduled_print": None, "ctx_minutes_since_model_cycle": None,
        "ctx_decided_probability": None, "ctx_book_imbalance": imbalance, "ctx_depth_shares": depth,
        "ctx_last_print_size": own[-1][1] if own else 0.0,
        "ctx_burst_prints": sum(1 for t, _ in own if t >= at_us - BURST_WINDOW_S * US),
        "ctx_sweep_bands": len({condition for _, condition, _ in recent}),
        "ctx_ft_info_clock": at_us, "ctx_ft_book": book_at,
        "ctx_ft_prints": max((t for t, _, _ in recent), default=None),
    }


def _marks(yes: _Book | None, fill_us: int, day_end_us: int, counts: Counter) -> dict:
    out = {}
    for horizon, seconds in MARK_HORIZONS:
        due = fill_us + seconds * US
        found = None
        if due >= day_end_us:
            counts[f"mark_{horizon}_due_after_utc_day"] += 1   # The next day folder is never read.
        elif yes is not None:
            index = bisect_left(yes.times, due)
            while index < len(yes.times) and yes.times[index] <= due + MARK_TOLERANCE_S * US:
                bid, ask = yes.bid[index], yes.ask[index]
                if not math.isnan(bid) and not math.isnan(ask):
                    found = (yes.times[index], (bid + ask) / 2)
                    break
                index += 1
        if found is None and due < day_end_us:
            counts[f"mark_{horizon}_no_two_sided_yes_book"] += 1
        out[f"mark_{horizon}_at_utc"] = None if found is None else found[0]
        out[f"mark_{horizon}_mid_yes"] = None if found is None else found[1]
    return out


def fill_id(token: str, minute_us: int, print_row: tuple) -> str:
    text = "|".join([TAPE_NAME, token, str(minute_us), *(repr(v) for v in print_row)])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def iter_day_rows(day: DayData, *, fill_rule: str, quote_size: float):
    """Yield ``("minute"|"fill", row)`` for every token, ordered by token then minute."""

    start, end = day_start_us(day.day), day_start_us(day.day) + DAY_US
    by_event = defaultdict(list)
    for token, rows in day.prints.items():
        condition = day.bands[token].condition_id
        by_event[day.bands[token].event_slug].extend((t, condition, size) for t, _, size, _ in rows)
    event_prints = {slug: _EventPrints(rows) for slug, rows in by_event.items()}
    empty = _EventPrints(())
    for book in day.books.values():
        book.sort()
    counts = day.dispositions
    for token in sorted(day.books):
        band, book = day.bands[token], day.books[token]
        side = band.side(token)
        prints = sorted(day.prints.get(token, ()))
        print_times = [p[0] for p in prints]
        events = event_prints.get(band.event_slug, empty)
        seen = set()
        for i, captured in enumerate(book.times):
            minute = -(-captured // MINUTE_US) * MINUTE_US
            if minute >= end:
                counts["minute_starts_next_utc_day"] += 1
                continue
            if minute in seen:
                counts["snapshot_same_minute_ignored"] += 1
                continue
            seen.add(minute)
            bid, ask = book.bid[i], book.ask[i]
            if math.isnan(bid) or not 0 < bid < 1:
                counts["minute_without_valid_bid"] += 1
                continue
            context = _context(day, band, side, captured, events)
            if context is None:
                counts["minute_after_close_or_past_event"] += 1
                continue
            common = {
                "utc_day": day.day.isoformat(), "condition_id": band.condition_id, "market_id": band.market_id,
                "station": band.station, "event_slug": band.event_slug, "event_date": band.event_date,
                "token_id": token, "maker_side": side, "minute_utc": minute, "quote_price": bid,
                "quote_ask": None if math.isnan(ask) else ask, "quote_snapshot_at_utc": captured,
            }
            yield "minute", {**common, **context, "basis": BASIS}
            first = bisect_left(print_times, minute)
            hits = [p for p in prints[first:bisect_left(print_times, minute + MINUTE_US)]
                    if crosses(fill_rule, p[1], bid)]
            if not hits:
                continue
            hit = hits[0]
            fill_context = _context(day, band, side, hit[0], events, book_strict=True)
            if fill_context is None:
                counts["fill_after_close"] += 1
                continue
            yield "fill", {
                **common, **fill_context, "fill_id": fill_id(token, minute, hit), "fill_at_utc": hit[0],
                "price": bid, "size": min(hit[2], quote_size), "quote_size": quote_size,
                "print_price": hit[1], "print_size": hit[2], "print_side": hit[3],
                "crossing_prints_in_minute": len(hits), "fill_rule": fill_rule,
                **_marks(day.books.get(band.yes_token), hit[0], end, counts),
                "settlement_p_yes": None, "basis": BASIS,
            }


# ---------------------------------------------------------------- contract checks (build 2 rules)


def contract_violation(kind: str, row: dict, max_date: date = MAX_DATE) -> str | None:
    """The first build 2 record rule a tape row breaks, else None (mirrors toxicity.parse_record + FillContext)."""

    times = [row["minute_utc"], row["ctx_at_utc"], row["ctx_ft_info_clock"], row["ctx_ft_book"], row["ctx_ft_prints"]]
    if kind == "fill":
        times += [row["fill_at_utc"]] + [row[f"mark_{h}_at_utc"] for h, _ in MARK_HORIZONS]
    dates = [from_us(t).date() for t in times if t is not None] + [row["event_date"]]
    if any(is_reserved(d) or d > max_date for d in dates):
        return "date_after_max_or_reserved"
    if row["maker_side"] not in ("YES", "NO"):
        return "maker_side"
    if type(row["ctx_horizon_days"]) is not int or row["ctx_horizon_days"] < 0 or row["ctx_minutes_to_close"] < 0:
        return "horizon_or_close"
    imbalance = row["ctx_book_imbalance"]
    if imbalance is not None and not -1 <= imbalance <= 1:
        return "imbalance"
    if row["ctx_depth_shares"] < 0 or row["ctx_last_print_size"] < 0 or row["ctx_burst_prints"] < 0 \
            or row["ctx_sweep_bands"] < 0:
        return "negative_feature"
    feature_times = [row["ctx_ft_info_clock"], row["ctx_ft_book"], row["ctx_ft_prints"]]
    if any(t is not None and t > row["ctx_at_utc"] for t in feature_times):
        return "feature_after_context"
    if row["ctx_ft_prints"] is not None and row["ctx_ft_prints"] >= row["ctx_at_utc"]:
        return "prints_not_before_context"
    if kind == "minute":
        return "context_after_minute" if row["ctx_at_utc"] > row["minute_utc"] else None
    if not 0 < row["price"] < 1 or not row["size"] > 0:
        return "price_or_size"
    if not row["minute_utc"] <= row["fill_at_utc"] < row["minute_utc"] + MINUTE_US:
        return "fill_outside_minute"
    if row["ctx_at_utc"] > row["fill_at_utc"]:
        return "context_after_fill"
    if row["ctx_ft_book"] is not None and row["ctx_ft_book"] >= row["fill_at_utc"]:
        return "book_not_before_fill"
    for horizon, seconds in MARK_HORIZONS:
        at = row[f"mark_{horizon}_at_utc"]
        due = row["fill_at_utc"] + seconds * US
        if at is not None and not due <= at <= due + MARK_TOLERANCE_S * US:
            return f"mark_{horizon}_window"
    return None


# ---------------------------------------------------------------- parquet


def _schemas():
    import pyarrow as pa

    ts = pa.timestamp("us", tz="UTC")
    common = [
        ("utc_day", pa.string()), ("condition_id", pa.string()), ("market_id", pa.string()),
        ("station", pa.string()), ("event_slug", pa.string()), ("event_date", pa.date32()),
        ("token_id", pa.string()), ("maker_side", pa.string()), ("minute_utc", ts),
        ("quote_price", pa.float64()), ("quote_ask", pa.float64()), ("quote_snapshot_at_utc", ts),
        ("ctx_at_utc", ts), ("ctx_horizon_days", pa.int32()), ("ctx_minutes_to_close", pa.float64()),
        ("ctx_minutes_from_scheduled_print", pa.float64()), ("ctx_minutes_since_model_cycle", pa.float64()),
        ("ctx_decided_probability", pa.float64()), ("ctx_book_imbalance", pa.float64()),
        ("ctx_depth_shares", pa.float64()), ("ctx_last_print_size", pa.float64()),
        ("ctx_burst_prints", pa.int32()), ("ctx_sweep_bands", pa.int32()),
        ("ctx_ft_info_clock", ts), ("ctx_ft_book", ts), ("ctx_ft_prints", ts),
    ]
    fill_only = [
        ("fill_id", pa.string()), ("fill_at_utc", ts), ("price", pa.float64()), ("size", pa.float64()),
        ("quote_size", pa.float64()), ("print_price", pa.float64()), ("print_size", pa.float64()),
        ("print_side", pa.string()), ("crossing_prints_in_minute", pa.int32()), ("fill_rule", pa.string()),
    ]
    for horizon, _ in MARK_HORIZONS:
        fill_only += [(f"mark_{horizon}_at_utc", ts), (f"mark_{horizon}_mid_yes", pa.float64())]
    fill_only += [("settlement_p_yes", pa.float64())]
    meta = {"tape": TAPE_NAME, "tape_revision": str(TAPE_REVISION), "basis": BASIS}
    return {
        MINUTES_TABLE: pa.schema(common + [("basis", pa.string())], metadata={**meta, "table": MINUTES_TABLE}),
        FILLS_TABLE: pa.schema(common + fill_only + [("basis", pa.string())], metadata={**meta, "table": FILLS_TABLE}),
    }


class _TableWriter:
    def __init__(self, path: Path, schema):
        import pyarrow.parquet as pq

        self.schema, self.rows, self.written = schema, [], 0
        self.writer = pq.ParquetWriter(long_path(path), schema, compression="zstd")

    def add(self, row: dict) -> None:
        self.rows.append(row)
        if len(self.rows) >= WRITE_BATCH_ROWS:
            self.flush()

    def flush(self) -> None:
        import pyarrow as pa

        columns = {name: [row[name] for row in self.rows] for name in self.schema.names}
        self.writer.write_table(pa.Table.from_pydict(columns, schema=self.schema))
        self.written += len(self.rows)
        self.rows = []

    def close(self) -> None:
        try:
            if self.rows or not self.written:
                self.flush()
        finally:
            self.writer.close()


def read_table_rows(path: Path, columns: list[str]):
    """Yield tuples of ``columns`` from a tape table; the file is closed before return."""

    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(long_path(path))
    try:
        for batch in parquet.iter_batches(batch_size=WRITE_BATCH_ROWS, columns=columns):
            yield from zip(*(batch.column(name).to_pylist() for name in columns))
    finally:
        parquet.close()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(long_path(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rename_create_only(source: Path, target: Path) -> None:
    if os.path.lexists(long_path(target)):
        raise FileExistsError(f"refusing to overwrite {target}")
    os.rename(long_path(source), long_path(target))  # Windows rename also refuses an existing target.


def _write_json_create_only(path: Path, payload: dict) -> None:
    temp = path.with_name(path.name + ".tmp")
    with open(long_path(temp), "x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    _rename_create_only(temp, path)


def _set_aside(path: Path, stamp: str) -> str | None:
    """Rename an interrupted attempt's file out of the way; never delete or overwrite it."""

    if not os.path.lexists(long_path(path)):
        return None
    target = path.with_name(f"{path.name}.orphan-{stamp}")
    _rename_create_only(path, target)
    return str(target)


# ---------------------------------------------------------------- one day


def export_day(root_day: Path, day: date, out_dir: Path, *, max_date: date, fill_rule: str, quote_size: float,
               stamp: str) -> dict:
    """Extract one UTC day folder and write its two tables; return the (unwritten) day receipt."""

    data = DayData(day, max_date)
    segments = list_segments(root_day)
    for segment in segments:
        try:
            data.read_segment(segment)
        except (JournalMismatch, OSError, EOFError, zlib.error, ValueError, KeyError) as exc:
            # A damaged segment (bad or truncated gzip, unreadable file) fails this day's checks: the day
            # gets a mismatch receipt and stays unsealed; the run continues with the next day.
            data.errors.append(f"{segment.name}: {type(exc).__name__}: {exc}"[:400])
    day_dir = out_dir / "tape" / f"utc_day={day.isoformat()}"
    os.makedirs(long_path(day_dir), exist_ok=True)
    schemas = _schemas()
    finals = {name: day_dir / f"{name}.parquet" for name in schemas}
    partials = {name: day_dir / f"{name}.parquet.partial" for name in schemas}
    orphans = [p for name in schemas for p in (_set_aside(finals[name], stamp), _set_aside(partials[name], stamp)) if p]
    writers = {name: _TableWriter(partials[name], schemas[name]) for name in schemas}
    violations, fill_ids, duplicate_fill_ids = Counter(), set(), 0
    minute_keys, fill_keys, by_side = set(), [], Counter()
    try:
        for kind, row in iter_day_rows(data, fill_rule=fill_rule, quote_size=quote_size):
            problem = contract_violation(kind, row, max_date)
            if problem:
                violations[f"{kind}:{problem}"] += 1
            if kind == "minute":
                minute_keys.add((row["token_id"], row["minute_utc"]))
                writers[MINUTES_TABLE].add(row)
            else:
                duplicate_fill_ids += row["fill_id"] in fill_ids
                fill_ids.add(row["fill_id"])
                fill_keys.append((row["token_id"], row["minute_utc"]))
                writers[FILLS_TABLE].add(row)
            by_side[f"{kind}:{row['maker_side']}"] += 1
    finally:
        for writer in writers.values():
            writer.close()
    readback = {MINUTES_TABLE: Counter(), FILLS_TABLE: Counter()}
    for name in schemas:
        for token, minute in read_table_rows(partials[name], ["token_id", "minute_utc"]):
            readback[name][(token, to_us(minute))] += 1
        _rename_create_only(partials[name], finals[name])
    written = {name: writers[name].written for name in schemas}
    checks = {
        "no_segment_or_journal_errors": not data.errors,
        "rows_obey_build2_record_contract": not violations,
        "fill_ids_unique": duplicate_fill_ids == 0,
        "every_fill_has_its_exposure_minute": all(key in minute_keys for key in fill_keys),
        "minute_keys_unique_per_token": sum(readback[MINUTES_TABLE].values()) == len(readback[MINUTES_TABLE]),
        "readback_rows_equal_written": all(sum(readback[n].values()) == written[n] for n in schemas),
        "readback_minute_keys_equal_written": set(readback[MINUTES_TABLE]) == minute_keys,
    }
    return {
        "receipt": DAY_RECEIPT_NAME, "receipt_revision": RECEIPT_REVISION,
        "tape": TAPE_NAME, "tape_revision": TAPE_REVISION, "basis": BASIS,
        "utc_day": day.isoformat(), "input_day_folder": str(root_day),
        "max_date": max_date.isoformat(), "fill_rule": fill_rule, "quote_size": quote_size,
        "segments": data.segments,
        "segments_read": data.stats["segments_read"],
        "unsealed_segments_skipped": data.stats["unsealed_segments_skipped"],
        "journals_read": data.stats["journals_read"], "journal_bytes_read": data.stats["journal_bytes_read"],
        "book_snapshots": data.stats["book_snapshots"],
        "tokens": len(data.books), "bands": len({b.condition_id for b in data.bands.values()}),
        "event_dates": sorted({b.event_date.isoformat() for b in data.bands.values()}),
        "dispositions": dict(sorted(data.dispositions.items())),
        "rows": {"minutes": written[MINUTES_TABLE], "fills": written[FILLS_TABLE], "by_kind_side": dict(sorted(by_side.items()))},
        "contract_violations": dict(violations),
        "errors": data.errors,
        "earlier_attempt_files_set_aside": orphans,
        "checks": checks,
        "match": all(checks.values()),
        "outputs": {name: {"path": str(finals[name]), "rows": written[name],
                           "bytes": os.path.getsize(long_path(finals[name])), "sha256": _sha256_file(finals[name])}
                    for name in schemas},
    }


# ---------------------------------------------------------------- run / dry run


def _receipt_names(out_dir: Path) -> list[str]:
    receipts = out_dir / "receipts"
    return os.listdir(long_path(receipts)) if os.path.isdir(long_path(receipts)) else []


def dry_run(root: Path, out_dir: Path, *, max_date: date = MAX_DATE, min_date: date | None = None) -> dict:
    """Stat-only plan: the allowed days, their segments and sizes, and an estimated output. Opens no file."""

    check_request(max_date, min_date)
    out_dir = check_out_dir(out_dir, root)
    days, skipped = list_days(root, max_date, min_date)
    names = set(_receipt_names(out_dir))
    rows = []
    for day, folder in sorted(days, reverse=True):
        segments = sealed = files = size = 0
        for segment in list_segments(folder):
            segments += 1
            with os.scandir(long_path(segment)) as entries:
                listed = [(e.name, e.stat().st_size) for e in entries if e.is_file()]
            sealed += any(n in ("manifest.json", "manifest.json.gz") for n, _ in listed)
            files += len(listed)
            size += sum(s for _, s in listed)
        key = day.isoformat()
        rows.append({"utc_day": key, "segments": segments, "sealed_segments": sealed,
                     "unsealed_segments": segments - sealed, "files": files, "input_bytes": size,
                     "done": f"{key}.json" in names,
                     "mismatch_receipts": sum(1 for n in names if n.startswith(f"{key}.mismatch-"))})
    todo = [r for r in rows if not r["done"]]
    todo_bytes = sum(r["input_bytes"] for r in todo)
    return {
        "receipt": DRY_RUN_NAME, "receipt_revision": RECEIPT_REVISION, "root": str(root), "out_dir": str(out_dir),
        "max_date": max_date.isoformat(), "min_date": min_date.isoformat() if min_date else None,
        "reserved_window": [RESERVED_FIRST.isoformat(), RESERVED_LAST.isoformat()],
        "folders_skipped_by_name": dict(skipped), "days": rows,
        "days_total": len(rows), "days_done": len(rows) - len(todo), "days_remaining": len(todo),
        "input_bytes": sum(r["input_bytes"] for r in rows), "remaining_input_bytes": todo_bytes,
        "estimated_output_bytes": int(todo_bytes * OUTPUT_PER_INPUT_BYTE_UNMEASURED),
        "estimate_basis": f"UNMEASURED placeholder: {OUTPUT_PER_INPUT_BYTE_UNMEASURED} output bytes per on-disk input byte",
        "file_contents_opened": 0,
    }


def check_backlog_fill_rule(out_dir: Path, fill_rule: str) -> None:
    """Refuse an output directory holding day receipts written under another fill rule.

    The resume key is the day receipt, so mixing rules in one backlog would silently skip days of
    the requested rule. Each rule gets its own backlog (the host wrapper uses ``backlog-<rule>``).
    """

    for name in sorted(_receipt_names(out_dir)):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(\.mismatch-\d{8}T\d{6}Z)?\.json", name):
            continue
        with open(long_path(out_dir / "receipts" / name), encoding="utf-8") as handle:
            found = json.load(handle).get("fill_rule")
        if found != fill_rule:
            raise TapeRefused(f"refused: {name} was written with fill rule {found!r}, not {fill_rule!r}; "
                              "use a separate --out-dir per fill rule")


def run(root: Path, out_dir: Path, *, max_date: date = MAX_DATE, min_date: date | None = None,
        fill_rule: str = "at_price", quote_size: float = QUOTE_SIZE, deadline: datetime | None = None,
        max_days: int | None = None, code_commit: str | None = None, now=None) -> dict:
    check_request(max_date, min_date)
    out_dir = check_out_dir(out_dir, root)
    if fill_rule not in FILL_RULES:
        raise TapeRefused(f"refused: --fill-rule must be one of {FILL_RULES}")
    if not (math.isfinite(quote_size) and quote_size > 0):
        raise TapeRefused("refused: --quote-size must be positive")
    if code_commit is not None and not COMMIT.fullmatch(code_commit):
        raise TapeRefused("refused: --code-commit must be a 40-hex commit")
    check_backlog_fill_rule(out_dir, fill_rule)
    clock = now or (lambda: datetime.now(timezone.utc))
    started = clock()
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    os.makedirs(long_path(out_dir / "receipts"), exist_ok=True)
    days, skipped = list_days(root, max_date, min_date)
    folders = dict(days)
    names = set(_receipt_names(out_dir))
    mismatched = {d for d in folders if any(n.startswith(f"{d.isoformat()}.mismatch-") for n in names)}
    order = sorted(folders, reverse=True)
    # Never-attempted days first (newest first), then days whose earlier attempt did not match.
    order = [d for d in order if d not in mismatched] + [d for d in order if d in mismatched]
    code = {"module": __name__, "module_sha256": _sha256_file(Path(__file__)), "commit": code_commit}
    summaries, extracted, stopped_reason = [], 0, None
    for day in order:
        receipt_path = out_dir / "receipts" / f"{day.isoformat()}.json"
        if os.path.exists(long_path(receipt_path)):
            summaries.append({"utc_day": day.isoformat(), "status": "already_sealed"})
            continue
        if max_days is not None and extracted >= max_days:
            stopped_reason = "max_days"
            break
        if deadline is not None and clock() >= deadline:
            stopped_reason = "deadline"
            break
        day_started = clock()
        receipt = export_day(folders[day], day, out_dir, max_date=max_date, fill_rule=fill_rule,
                             quote_size=quote_size, stamp=stamp)
        extracted += 1
        receipt.update(code=code, started_at=day_started.isoformat(), finished_at=clock().isoformat())
        if not receipt["match"]:
            receipt_path = out_dir / "receipts" / f"{day.isoformat()}.mismatch-{stamp}.json"
        _write_json_create_only(receipt_path, receipt)
        summaries.append({"utc_day": day.isoformat(), "status": "extracted", "receipt": receipt_path.name,
                          "match": receipt["match"], "minutes": receipt["rows"]["minutes"],
                          "fills": receipt["rows"]["fills"],
                          "journal_bytes_read": receipt["journal_bytes_read"],
                          "output_bytes": sum(o["bytes"] for o in receipt["outputs"].values())})
    run_receipt = {
        "receipt": RUN_RECEIPT_NAME, "receipt_revision": RECEIPT_REVISION, "root": str(root),
        "max_date": max_date.isoformat(), "min_date": min_date.isoformat() if min_date else None,
        "reserved_window": [RESERVED_FIRST.isoformat(), RESERVED_LAST.isoformat()],
        "fill_rule": fill_rule, "quote_size": quote_size, "folders_skipped_by_name": dict(skipped),
        "days_available": len(folders), "input_days": [d.isoformat() for d in sorted(folders)],
        "days": summaries, "days_extracted": extracted,
        "days_remaining": sum(1 for d in folders
                              if not os.path.exists(long_path(out_dir / "receipts" / f"{d.isoformat()}.json"))),
        "all_match": all(row.get("match", True) for row in summaries),
        "stopped_reason": stopped_reason, "started_at": started.isoformat(), "finished_at": clock().isoformat(),
        "code": code,
    }
    _write_json_create_only(out_dir / f"run_receipt_{stamp}.json", run_receipt)
    return run_receipt


# ---------------------------------------------------------------- build 2 adapter


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value.isoformat()


def _context_payload(row: dict) -> dict:
    times = {"info_clock": row["ctx_ft_info_clock"], "book": row["ctx_ft_book"], "prints": row["ctx_ft_prints"]}
    return {
        "at_utc": _iso(row["ctx_at_utc"]), "maker_side": row["maker_side"],
        "horizon_days": int(row["ctx_horizon_days"]), "minutes_to_close": row["ctx_minutes_to_close"],
        "minutes_from_scheduled_print": row["ctx_minutes_from_scheduled_print"],
        "minutes_since_model_cycle": row["ctx_minutes_since_model_cycle"],
        "decided_probability": row["ctx_decided_probability"], "book_imbalance": row["ctx_book_imbalance"],
        "depth_shares": row["ctx_depth_shares"], "last_print_size": row["ctx_last_print_size"],
        "burst_prints": int(row["ctx_burst_prints"]), "sweep_bands": int(row["ctx_sweep_bands"]),
        "feature_times": {k: _iso(v) for k, v in sorted(times.items()) if v is not None},
    }


def record_payloads(kind: str, row: dict, settlement: dict | None = None) -> dict:
    """One build 2 neutral JSONL record (``toxicity.parse_record`` input) from one tape row."""

    payload = {"kind": kind, "condition_id": row["condition_id"], "market_id": row["market_id"],
               "event_date": row["event_date"].isoformat(), "minute_utc": _iso(row["minute_utc"]),
               "context": _context_payload(row), "basis": row["basis"]}
    if kind == "fill":
        marks = {h: {"observed_at_utc": _iso(row[f"mark_{h}_at_utc"]), "mid_yes": row[f"mark_{h}_mid_yes"]}
                 for h, _ in MARK_HORIZONS if row[f"mark_{h}_at_utc"] is not None}
        p_yes, observed = (settlement or {}).get(row["condition_id"], (None, None))
        payload.update(fill_id=row["fill_id"], fill_at_utc=_iso(row["fill_at_utc"]), maker_side=row["maker_side"],
                       price=row["price"], size=row["size"], marks=marks, settlement_p_yes=p_yes,
                       settlement_observed_at_utc=observed)
    return payload


def _payload_dates(payload: dict):
    out = [payload["event_date"], payload["minute_utc"], payload.get("fill_at_utc"),
           payload.get("settlement_observed_at_utc"), payload["context"]["at_utc"]]
    out += [m["observed_at_utc"] for m in (payload.get("marks") or {}).values()]
    out += list(payload["context"]["feature_times"].values())
    return [date.fromisoformat(v[:10]) for v in out if v is not None]


def to_jsonl(tape_dir: Path, output: Path, *, maker_side: str, settlement_path: Path | None = None,
             days: list[date] | None = None) -> dict:
    """Write sealed days of one maker side as build 2 JSONL (create-only).

    Build 2 keys exposure minutes by ``(condition_id, minute_utc)``, so one file
    holds one maker side. Each table's SHA-256 is checked against its day
    receipt before it is read; every record date is checked against the
    reserved window and ``MAX_DATE`` before it is written.

    Settlements: a fill's settlement label is withheld (``settlement_p_yes`` null) when none is given for
    its condition, when it was observed before the fill, or when it was observed on or after 2026-09-30
    (the reserved window; it can never enter the fit). The fill itself is kept so the exposure-minute
    hazard is not biased, and each reason is counted in ``<output>.receipt.json`` (create-only).
    """

    if maker_side not in ("YES", "NO"):
        raise TapeRefused("refused: --maker-side must be YES or NO")
    settlement = None
    if settlement_path is not None:
        # {condition_id: {"p_yes": float, "observed_at_utc": ISO time with offset}}; build 2 (4ae3602fa) needs
        # the observation time, dates it against the embargo, and refuses one before the fill.
        settlement = {}
        with open(settlement_path, encoding="utf-8") as handle:
            for key, value in json.load(handle).items():
                if not isinstance(value, dict) or "observed_at_utc" not in value:
                    raise TapeRefused("refused: each settlement needs p_yes and observed_at_utc")
                p_yes = float(value["p_yes"])
                observed = datetime.fromisoformat(str(value["observed_at_utc"]).replace("Z", "+00:00"))
                if not 0 <= p_yes <= 1 or observed.tzinfo is None:
                    raise TapeRefused("refused: settlement p_yes must lie in [0, 1] with an offset-aware time")
                settlement[str(key).lower()] = (p_yes, _iso(observed))
    sealed = sorted(date.fromisoformat(n[:-5]) for n in _receipt_names(tape_dir) if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", n))
    chosen = [d for d in sealed if days is None or d in days]
    if days is not None and set(days) - set(chosen):
        raise TapeRefused("refused: a requested day is not sealed")
    if any(is_reserved(d) or d > MAX_DATE for d in chosen):
        raise TapeRefused("refused: a sealed day lies after the tape's maximum date")
    columns = list(_schemas()[FILLS_TABLE].names)
    minute_columns = list(_schemas()[MINUTES_TABLE].names)
    counts, withheld = Counter(), Counter({reason: 0 for reason in SETTLEMENT_WITHHELD_REASONS})
    receipt_path = Path(f"{output}.receipt.json")
    if os.path.exists(receipt_path):
        raise FileExistsError(str(receipt_path))
    with open(output, "x", encoding="utf-8", newline="\n") as handle:
        for day in chosen:
            with open(tape_dir / "receipts" / f"{day.isoformat()}.json", encoding="utf-8") as receipt_file:
                receipt = json.load(receipt_file)
            for kind, table, names in (("minute", MINUTES_TABLE, minute_columns), ("fill", FILLS_TABLE, columns)):
                path = tape_dir / "tape" / f"utc_day={day.isoformat()}" / f"{table}.parquet"
                if _sha256_file(path) != receipt["outputs"][table]["sha256"]:
                    raise TapeRefused(f"refused: {path} differs from its day receipt")
                for values in read_table_rows(path, names):
                    row = dict(zip(names, values))
                    if row["maker_side"] != maker_side:
                        continue
                    usable = None
                    if kind == "fill":
                        reason, usable = _settlement_for(row, settlement)
                        if reason:
                            withheld[reason] += 1
                    payload = record_payloads(kind, row, usable)
                    if any(is_reserved(d) or d > MAX_DATE for d in _payload_dates(payload)):
                        raise TapeRefused("refused: a record date lies after the tape's maximum date")
                    handle.write(json.dumps(payload, sort_keys=True, allow_nan=False) + "\n")
                    counts[kind] += 1
    summary = {"receipt": ADAPTER_RECEIPT_NAME, "receipt_revision": RECEIPT_REVISION,
               "output": str(output), "maker_side": maker_side, "days": [d.isoformat() for d in chosen],
               "settlement_json": None if settlement_path is None else str(settlement_path),
               "settlement_json_sha256": None if settlement_path is None else _sha256_file(Path(settlement_path)),
               "minutes": counts["minute"], "fills": counts["fill"],
               "fills_with_settlement": counts["fill"] - sum(withheld.values()),
               "fills_settlement_withheld": dict(withheld),
               "settlement_withheld_note": "fill kept with settlement_p_yes null; settlement-horizon label lost",
               "sha256": _sha256_file(output)}
    _write_json_create_only(receipt_path, summary)
    return {**summary, "receipt_path": str(receipt_path)}


def _settlement_for(row: dict, settlement: dict | None) -> tuple[str | None, dict | None]:
    """(withheld reason or None, ``{condition_id: (p_yes, observed)}`` for a usable settlement)."""

    found = (settlement or {}).get(row["condition_id"])
    if found is None:
        return "no_settlement_given", None
    observed = datetime.fromisoformat(found[1])
    fill_at = row["fill_at_utc"] if isinstance(row["fill_at_utc"], datetime) else from_us(row["fill_at_utc"])
    if observed < fill_at:
        return "observed_before_fill", None
    day = observed.astimezone(timezone.utc).date()
    if is_reserved(day) or day > MAX_DATE:
        return "observed_on_or_after_2026_09_30", None
    return None, {row["condition_id"]: found}


# ---------------------------------------------------------------- CLI


def _deadline(value: str | None) -> datetime | None:
    if not value:
        return None
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise argparse.ArgumentTypeError("--deadline needs an offset")
    return moment


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m weather.market.maker_counterfactual_tape",
                                     description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="Extract sealed 88a days into the counterfactual tape.")
    export.add_argument("--root", type=Path, default=None, help="88a root; default data/maker_evidence.")
    export.add_argument("--out-dir", type=Path, required=True, help="Output root outside the data tree.")
    export.add_argument("--max-date", type=date.fromisoformat, default=MAX_DATE)
    export.add_argument("--min-date", type=date.fromisoformat, default=None)
    export.add_argument("--fill-rule", choices=FILL_RULES, default="at_price")
    export.add_argument("--quote-size", type=float, default=QUOTE_SIZE)
    export.add_argument("--deadline", default=None, help="ISO time with offset; no new day starts at or after it.")
    export.add_argument("--max-days", type=int, default=None, help="At most N new days (sealed days are not counted).")
    export.add_argument("--code-commit", default=None, help="Checkout HEAD recorded in every receipt.")
    export.add_argument("--dry-run", action="store_true", help="Stat-only plan; opens no file.")
    adapter = sub.add_parser("to-jsonl", help="Write sealed days of one side as build 2 JSONL records.")
    adapter.add_argument("--tape-dir", type=Path, required=True)
    adapter.add_argument("--output", type=Path, required=True)
    adapter.add_argument("--maker-side", choices=("YES", "NO"), required=True)
    adapter.add_argument("--settlement-json", type=Path, default=None,
                         help="{condition_id: {p_yes, observed_at_utc}} map.")
    adapter.add_argument("--day", type=date.fromisoformat, action="append", default=None)
    args = parser.parse_args(argv)
    try:
        if args.command == "to-jsonl":
            print(json.dumps(to_jsonl(args.tape_dir, args.output, maker_side=args.maker_side,
                                      settlement_path=args.settlement_json, days=args.day), sort_keys=True))
            return 0
        root = args.root or data_path("maker_evidence")
        if args.dry_run:
            print(json.dumps(dry_run(root, args.out_dir, max_date=args.max_date, min_date=args.min_date),
                             indent=1, sort_keys=True))
            return 0
        receipt = run(root, args.out_dir, max_date=args.max_date, min_date=args.min_date, fill_rule=args.fill_rule,
                      quote_size=args.quote_size, deadline=_deadline(args.deadline), max_days=args.max_days,
                      code_commit=args.code_commit)
    except TapeRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({key: receipt[key] for key in ("days_available", "days_extracted", "days_remaining",
                                                    "all_match", "stopped_reason")}, sort_keys=True))
    return 0 if receipt["all_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
