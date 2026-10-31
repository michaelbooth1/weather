r"""MG-2 daily input exporter, capture-host side: one read-only, outcome-free bundle per target date.

Binding plan section 9 (docs/research/mg2-composite-binding-2026-10-25/binding-plan.md, sections 9.1-9.3) and
``weather.calibration.mg2_input_allowlist`` (the shared contract; its ``allowlist_sha256()`` goes into every
manifest). The workstation receiver (the C7 ``receive`` command) verifies what this writes.

A manual one-shot. It imports only the standard library and ``mg2_input_allowlist`` (itself stdlib only), so
it never refuses on the capture host and no capture loop imports it (roll-free).

* **Known paths only.** It opens nothing but the files named in ``SOURCE_PATTERNS`` under
  ``<data-root>\snapshots\<slug>\`` for the 11 fixed markets and ``<data-root>\forecast_payload_cas\sha256\``;
  every path is checked against those patterns, and every component against links and reparse points, before
  it is opened. Anything else fails closed.
* **Shared-read, bounded opens.** On Windows every read handle is ``CreateFileW`` with read, write and delete
  sharing, so a capture writer can append to, rename or delete a file the exporter is reading. Every file is read
  once, front to back, as the BOUNDED byte range ``[0, size at open)`` (``_BoundedReader``): bytes a writer appends
  after the open are never read, a file is never followed or re-read (no tail), and no whole-file helper
  (``ReadLines``, ``read()``) is used. Text files yield complete lines only; an unterminated final line (a write
  in progress at the open) is dropped and its byte count recorded per file as ``partial_tail_bytes``. Lines
  stream straight into the staging bundle (blobs in 1 MiB chunks), so memory stays flat.
* **Read mode per input path** (D = target date; every one bounded to its size at open):

  - ``snapshots/<D-1|D>/replay_inputs.jsonl``: append-only tape; bounded range, complete lines; rows captured
    after the export cut are dropped.
  - ``snapshots/<D>/snapshots_long.csv``, ``snapshots/<D>/features_long.csv``: rewritable; opened only when
    quiet for at least 30 minutes (a closed day), then the bounded range.
  - ``snapshots/<D-1|D|D+1>/forecast_payloads.jsonl``: append-only (D+1 is the live day); bounded range, NBM
    rows captured by the cut only.
  - ``snapshots/<D-1|D|D+1>/forecast_payloads_long.csv``: fallback when the JSONL is absent; quiet guard, then
    the bounded range.
  - ``forecast_payload_cas/sha256/<hh>/<sha256>.blob``: create-once and immutable; the whole file, re-hashed.
* **Quiet guard.** ``snapshots_long.csv``, ``features_long.csv`` and ``forecast_payloads_long.csv`` can be
  rewritten in place by a capture writer (``SnapshotStore.append_csv`` widens a grown header through a temp
  file and ``os.replace``; ``snapshot_store_backfill`` does the same), and Windows refuses that replace while
  any reader holds the file. Such a file is opened only when its mtime is at least ``MIN_QUIET_SECONDS`` old;
  otherwise the date is refused (exit 3) naming the file. The other files are append-only (the JSONL tapes,
  ``order_books_summary.csv``, ``market_ws_events.csv``, execution-tape trades) or create-once (NBM blobs).
* **Dates.** A target date D is exported only if every event folder it reads (D-1, D, D+1) is on or before
  2026-09-29 (the development window, so D <= 2026-09-28) or D >= D0 (2026-10-28; the MG-2 reservation
  exemption, option 2), and only after D's export cut has passed.
* **Projection, not copy.** Every record goes through the allow-list's projections; only rows captured at or
  before the export cut travel. NBM blobs are copied byte for byte after re-hashing.
* **Self-check.** Every projected record is checked with the allow-list's own ``*_problems`` functions (the
  receiver's section 9.2 checks). METAR rows travel whole, so a forbidden or unlisted key inside one refuses the
  date (exit 2; key names only, never values) and nothing is published.
* **Coverage counts: OPT-IN, OFF by default** (``--coverage-counts``; master 2026-10-27, option c). Each use
  needs master's ruling first; the scheduled task never sets it, so a default run opens only the paths listed
  above (binding plan section 9.1). When set, and only then: ``market_price_coverage`` (B-1 section 3: per market, D's local 07-16 snapshots and how many
  carry a capture-time price on every band) and ``book_coverage`` (PT-1: rows of ``order_books_summary.csv``
  (or ``.csv.gz``) and ``market_ws_events.csv`` (or ``.csv.gz``) by local hour of D, and
  ``execution_tape\trades-*.jsonl`` line counts) are integers in the manifest. No price, book or trade value is
  written.

Output, all under the declared output directory ``<out>`` (default ``<repo>\data\exports\mg2-inputs``) and
nowhere else: ``<out>\<D>\`` (the bundle; ``manifest.json.sha256`` written last, then the folder is published by an
atomic rename from ``<out>\.<D>.partial``, which a failed run removes) and ``<out>\<D>.SHA256SUMS`` beside it
(outside the bundle, which must hold only allow-listed paths).

    python -m weather.calibration.mg2_input_export --date 2026-09-29 [--date ...] [--data-root <repo>\data]
        [--out <repo>\data\exports\mg2-inputs] [--coverage-counts  (OFF by default; master's ruling first)]
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import stat
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.calibration import mg2_input_allowlist as allow

SCHEMA = "mg2_input_export/1"
DEV_LAST = date(2026, 9, 29)
FORWARD_FIRST = date(2026, 10, 28)  # MG-2 D0: option 2 exempts MG-2's dates from here
SUMS_SUFFIX = ".SHA256SUMS"
COVERAGE_HOURS = (7, 16)
MIN_QUIET_SECONDS = 30 * 60
CHUNK = 1 << 20
TZ = {"atlanta": "America/New_York", "austin": "America/Chicago", "chicago": "America/Chicago",
      "dallas": "America/Chicago", "denver": "America/Denver", "houston": "America/Chicago",
      "los-angeles": "America/Los_Angeles", "miami": "America/New_York", "nyc": "America/New_York",
      "san-francisco": "America/Los_Angeles", "seattle": "America/Los_Angeles"}
# Every file this exporter may open, relative to the data root (posix). Nothing else is ever opened.
SOURCE_PATTERNS = (
    re.compile(r"^snapshots/(?P<slug>[a-z0-9-]+)/(?P<name>replay_inputs\.jsonl|snapshots_long\.csv|"
               r"features_long\.csv|forecast_payloads\.jsonl|forecast_payloads_long\.csv|"
               r"order_books_summary\.csv|order_books_summary\.csv\.gz|market_ws_events\.csv|"
               r"market_ws_events\.csv\.gz)$"),
    re.compile(r"^snapshots/(?P<slug>[a-z0-9-]+)/execution_tape/trades-\d{5}\.jsonl$"),
    re.compile(r"^forecast_payload_cas/sha256/[0-9a-f]{2}/[0-9a-f]{64}\.blob$"),
)
# The section 9.1 inputs: the only paths a default (scheduled) run may open.
INPUT_PATTERNS = (
    re.compile(r"^snapshots/(?P<slug>[a-z0-9-]+)/(?P<name>replay_inputs\.jsonl|snapshots_long\.csv|"
               r"features_long\.csv|forecast_payloads\.jsonl|forecast_payloads_long\.csv)$"),
    SOURCE_PATTERNS[2],
)
# Files a capture writer may replace in place (temp file + os.replace): opened only once quiet.
REPLACEABLE = frozenset({"snapshots_long.csv", "features_long.csv", "forecast_payloads_long.csv"})
PRICE_COLUMN = "market_yes"  # read only to count presence; the value is never kept or written


class ExportRefused(RuntimeError):
    """The export cannot run (date, path, link or output); nothing is published."""


class FileTooFresh(ExportRefused):
    """A rewritable source file changed less than ``MIN_QUIET_SECONDS`` ago; nothing is published."""


# ----------------------------------------------------------------------------- reading

def _share_all_open(path):
    """A binary read handle that lets writers append, rename or delete the file (Windows); plain elsewhere."""
    if os.name != "nt":
        return open(path, "rb")
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                       wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    handle = create(str(path), 0x80000000,  # GENERIC_READ
                    0x00000007,  # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
                    None, 3, 0x00000080, None)  # OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), f"cannot open {path}")
    fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    return os.fdopen(fd, "rb")


class _BoundedReader:
    """The byte range ``[0, size at open)`` of a shared-read handle: bounded reads and complete lines only."""

    def __init__(self, raw, limit, record):
        self.raw, self.remaining, self.record = raw, limit, record

    def read(self, size=-1):
        if size is None or size < 0:
            raise ValueError("unbounded read refused")
        size = min(size, self.remaining)
        if size <= 0:
            return b""
        data = self.raw.read(size)
        self.remaining -= len(data)
        return data

    def lines(self):
        """Complete ``\\n``-terminated byte lines; an unterminated tail is dropped and its size recorded."""
        pending = b""
        while True:
            chunk = self.read(CHUNK)
            if not chunk:
                break
            parts = (pending + chunk).split(b"\n")
            pending = parts.pop()
            for part in parts:
                yield part + b"\n"
        self.record["partial_tail_bytes"] = len(pending)

    def __iter__(self):
        return self.lines()


class Source:
    """The host data root; every open goes through ``binary``/``text``, which admit only ``SOURCE_PATTERNS``."""

    def __init__(self, root, clock=time.time, coverage_counts=False):
        root = Path(root)
        if not root.is_absolute() or not root.is_dir() or not (root / "snapshots").is_dir():
            raise ExportRefused(f"data root {root} is not an absolute directory with snapshots/")
        self.root = root
        self.clock = clock
        self.coverage_counts = bool(coverage_counts)
        self.opened = {}  # rel -> {"source_bytes", "source_mtime_utc"} at open time

    def known(self, rel):
        """A listed file name, in one of the 11 markets' event folders or the shared NBM store.

        Without ``coverage_counts`` only the section 9.1 inputs (``INPUT_PATTERNS``) are known.
        """
        for pattern in (SOURCE_PATTERNS if self.coverage_counts else INPUT_PATTERNS):
            match = pattern.match(rel)
            if match:
                slug = match.groupdict().get("slug")
                return slug is None or allow.parse_slug(slug) is not None
        return False

    def path(self, rel):
        if not self.known(rel):
            raise ExportRefused(f"unknown source path refused: {rel}")
        full = self.root.joinpath(*rel.split("/"))
        here = self.root
        for part in rel.split("/"):
            here = here / part
            if not os.path.lexists(here):
                return None
            info = os.lstat(here)
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ExportRefused(f"link or reparse point refused: {rel}")
        if not stat.S_ISREG(os.lstat(full).st_mode):
            raise ExportRefused(f"not a regular file: {rel}")
        return full

    @contextlib.contextmanager
    def binary(self, rel):
        """A bounded shared-read reader on a known file; yields None when absent. Applies the quiet guard."""
        full = self.path(rel)
        if full is None:
            yield None
            return
        info = os.stat(full)
        if rel.rsplit("/", 1)[-1] in REPLACEABLE:
            age = self.clock() - info.st_mtime
            if age < MIN_QUIET_SECONDS:
                raise FileTooFresh(f"{rel} changed {max(age, 0):.0f} s ago (< {MIN_QUIET_SECONDS} s): a capture "
                                   f"writer may rewrite it in place; re-run once it is quiet")
        with _share_all_open(full) as raw:
            size = os.fstat(raw.fileno()).st_size  # the bound: bytes appended after this open are never read
            record = {"source_bytes": size, "read_mode": "bounded_range_at_open",
                      "source_mtime_utc": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat()}
            self.opened[rel] = record
            yield _BoundedReader(raw, size, record)

    @contextlib.contextmanager
    def text(self, rel):
        """Complete text lines of a known file, streamed from its bounded range; yields None when absent.

        ``.gz`` (opt-in coverage only) is decompressed from the bounded compressed range; a member still being
        written ends the stream.
        """
        with self.binary(rel) as reader:
            if reader is None:
                yield None
                return
            if rel.endswith(".gz"):
                yield _gzip_lines(reader)
            else:
                yield (line.decode("utf-8") for line in reader.lines())

    def is_cold_archived(self, slug):
        """True when the folder carries the cold-archive marker (existence check only; nothing opened)."""
        return os.path.lexists(self.root / "snapshots" / slug / ".cold_archive")

    def trade_files(self, slug):
        if not self.coverage_counts:
            raise ExportRefused("execution-tape trade files are coverage reads: --coverage-counts is off")
        if allow.parse_slug(slug) is None:
            raise ExportRefused(f"unknown event folder refused: {slug}")
        folder = self.root / "snapshots" / slug / "execution_tape"
        for here in (folder.parent, folder):
            if not os.path.lexists(here):
                return []
            info = os.lstat(here)
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ExportRefused(f"link or reparse point refused: {here.relative_to(self.root).as_posix()}")
        if not stat.S_ISDIR(os.lstat(folder).st_mode):
            return []
        names = sorted(n for n in os.listdir(folder) if re.fullmatch(r"trades-\d{5}\.jsonl", n))
        return [f"snapshots/{slug}/execution_tape/{n}" for n in names]


def _gzip_lines(reader):
    with gzip.GzipFile(fileobj=reader, mode="rb") as stream:
        try:
            for line in io.TextIOWrapper(stream, encoding="utf-8", newline=""):
                yield line
        except EOFError:  # the bounded range ended inside a member still being written
            return


def parse_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _jsonl_records(handle):
    for line in handle:
        if line.strip():
            yield json.loads(line)


def _jsonl_line(record):
    return (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


class _CsvLine:
    """One CSV row as bytes, with the bundle's dialect (``\\n`` line ends)."""

    def __init__(self):
        self.buffer = io.StringIO()
        self.writer = csv.writer(self.buffer, lineterminator="\n")

    def __call__(self, values):
        self.buffer.seek(0)
        self.buffer.truncate()
        self.writer.writerow(values)
        return self.buffer.getvalue().encode("utf-8")


# ----------------------------------------------------------------------------- writing

class Bundle:
    """The staging bundle: every output file is streamed in, hashed and counted as it is written."""

    def __init__(self, staging, day):
        self.staging, self.day = staging, day
        self.entries = {}

    @contextlib.contextmanager
    def file(self, rel, source_rel, src, rows_kind=True):
        if allow.classify_path(rel, self.day) is None:
            raise ExportRefused(f"internal: {rel} is not an allow-listed bundle path")
        target = self.staging.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        out = _OutFile(target, rows_kind)
        try:
            with open(target, "xb") as out.handle:
                yield out
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        if out.discard:
            target.unlink()
            return
        self.entries[rel] = {"path": rel, "sha256": out.sha.hexdigest(), "bytes": out.bytes,
                             "rows": out.rows if rows_kind else None, "source_path": source_rel,
                             **src.opened.get(source_rel, {})}


class _OutFile:
    def __init__(self, path, rows_kind):
        self.path, self.handle, self.sha = path, None, hashlib.sha256()
        self.bytes = self.rows = 0
        self.discard = False

    def write(self, data, row=True):
        self.handle.write(data)
        self.sha.update(data)
        self.bytes += len(data)
        self.rows += int(row)


# ----------------------------------------------------------------------------- dates

def check_date(day, now=None):
    """Every folder read (D-1, D, D+1) is <= 2026-09-29, or D >= D0 (option 2); and D's export cut has passed."""
    if day + timedelta(days=1) > DEV_LAST and day < FORWARD_FIRST:
        raise ExportRefused(f"{day} reads event folders after {DEV_LAST} (its D+1 folder) and is before MG-2's D0 "
                            f"{FORWARD_FIRST}: refused")
    now = now or datetime.now(timezone.utc)
    if now <= allow.export_cut_utc(day):
        raise ExportRefused(f"{day}'s export cut {allow.export_cut_utc(day).isoformat()} has not passed")


# ----------------------------------------------------------------------------- one bundle

def _local(market, captured):
    return captured.astimezone(ZoneInfo(TZ[market]))


def _in_cut(record, cut):
    captured = parse_time(record.get("captured_at_utc"))
    return captured is not None and captured <= cut


def _priced(value):
    value = str(value or "").strip()
    try:
        return value != "" and float(value) == float(value)
    except ValueError:
        return False


def _self_check(problems, rel):
    """Refuse the date when a projected record still carries a forbidden or unlisted key (names only)."""
    if problems:
        raise ExportRefused(f"forbidden or unlisted field in projected {rel}: {sorted(set(problems))[:10]}")


def _project_market(src, bundle, market, day, cut, counts):
    """Stream the D, D-1 and D+1 files of one market into the bundle.

    Returns ``(present, reason, nbm_refs, price_coverage)``; ``price_coverage`` is None unless
    ``src.coverage_counts``.
    """
    slug = allow.slug_for(market, day)
    reason, refs = None, {}
    # F1 replay inputs (D)
    rel = f"snapshots/{slug}/replay_inputs.jsonl"
    with src.text(rel) as handle:
        if handle is None:
            reason = "cold_archived_restore_first" if src.is_cold_archived(slug) else "replay_inputs_missing"
        else:
            with bundle.file(rel, rel, src) as out:
                for record in _jsonl_records(handle):
                    if _in_cut(record, cut):
                        kept = allow.project_replay_record(record)
                        _self_check(allow.replay_record_problems(kept), rel)
                        out.write(_jsonl_line(kept))
                    else:
                        counts["dropped_after_cut"] += 1
                if out.rows == 0:
                    out.discard = True
                    reason = "no_replay_inputs_before_cut"
    # F2 band tape (D) plus the B-1 price coverage counts in the same pass; F3 features (D)
    snaps, coverage_present = {}, False
    line = _CsvLine()
    for name in ("snapshots_long.csv", "features_long.csv"):
        rel = f"snapshots/{slug}/{name}"
        fields = allow.CSV_FIELDS[name]
        _self_check([f"forbidden:{k}" for k in fields if allow.forbidden(k)], rel)
        with src.text(rel) as handle:
            if handle is None:
                reason = reason or f"{name}_missing"
                continue
            coverage_present = coverage_present or name == "snapshots_long.csv"
            with bundle.file(rel, rel, src) as out:
                out.write(line(fields), row=False)
                for row in csv.DictReader(handle):
                    captured = parse_time(row.get("captured_at_utc"))
                    if captured is None or captured > cut:
                        counts["dropped_after_cut"] += 1
                        continue
                    out.write(line([row.get(k, "") or "" for k in fields]))
                    if name != "snapshots_long.csv" or not src.coverage_counts:
                        continue
                    local = _local(market, captured)
                    if local.date() == day and COVERAGE_HOURS[0] <= local.hour <= COVERAGE_HOURS[1]:
                        sid = row.get("snapshot_id")
                        snaps[sid] = snaps.get(sid, True) and _priced(row.get(PRICE_COLUMN))
    price = ({"snapshots_07_16": len(snaps), "priced_07_16": sum(snaps.values()), "source_present": coverage_present}
             if src.coverage_counts else None)
    # F1b: D-1's last snapshot (captured by the cut), METAR rows only
    prev = allow.slug_for(market, day - timedelta(days=1))
    rel = f"snapshots/{prev}/replay_inputs.jsonl"
    with src.text(rel) as handle:
        last, last_at = None, None
        for record in _jsonl_records(handle) if handle is not None else ():
            captured = parse_time(record.get("captured_at_utc"))
            if captured is not None and captured <= cut and (last_at is None or captured >= last_at):
                last, last_at = allow.project_prev_day_record(record), captured
    if last is not None:
        _self_check(allow.prev_day_record_problems(last), rel)
        with bundle.file(f"prev_day/{prev}/metar_rows.jsonl", rel, src) as out:
            out.write(_jsonl_line(last))
    # F4: NBM manifest rows of the D-1, D and D+1 folders (JSONL, else the long CSV)
    for offset in allow.PATHS["nbm_manifest"]["days"]:
        fslug = allow.slug_for(market, day + timedelta(days=offset))
        target = f"snapshots/{fslug}/forecast_payloads.jsonl"
        for name, reader in (("forecast_payloads.jsonl", _jsonl_records), ("forecast_payloads_long.csv",
                                                                          csv.DictReader)):
            rel = f"snapshots/{fslug}/{name}"
            with src.text(rel) as handle:
                if handle is None:
                    continue
                with bundle.file(target, rel, src) as out:
                    for row in reader(handle):
                        if row.get("source") != allow.NBM_SOURCE or not _in_cut(row, cut):
                            continue
                        kept = allow.project_row(row, allow.NBM_FIELDS)
                        _self_check(allow.nbm_row_problems(kept), rel)
                        out.write(_jsonl_line(kept))
                        digest = str(kept.get("payload_hash") or "")
                        if kept.get("payload_storage_scope") != allow.NBM_SCOPE:
                            continue
                        if kept.get("payload_ref") == allow.blob_ref(digest) and allow.BLOB_RE.match(
                                str(kept.get("payload_ref"))):
                            refs[digest] = kept["payload_ref"]
                        else:
                            counts["nbm_bad_ref"] += 1
            break
    return reason is None, reason, refs, price


def _hour_counts(lines, column, market, day):
    """Rows by local hour of D from a timestamp column (counts only), plus the total row count."""
    total, by_hour = 0, {}
    for row in csv.DictReader(lines):
        total += 1
        when = parse_time(row.get(column))
        if when is None:
            continue
        local = _local(market, when)
        if local.date() == day:
            by_hour[local.hour] = by_hour.get(local.hour, 0) + 1
    return total, {f"{h:02d}": n for h, n in sorted(by_hour.items())}


def book_coverage(src, market, day):
    """PT-1 counts: order-book summary and market websocket rows by local hour of D; execution-tape trade lines."""
    slug = allow.slug_for(market, day)
    out = {}
    for key, column in (("order_books_summary", "captured_at_utc"), ("market_ws_events", "received_at_utc")):
        entry = {"present": False, "file": None, "rows": 0, "rows_by_local_hour": {}}
        for name in (f"{key}.csv", f"{key}.csv.gz"):
            with src.text(f"snapshots/{slug}/{name}") as lines:
                if lines is None:
                    continue
                total, by_hour = _hour_counts(lines, column, market, day)
            entry = {"present": True, "file": name, "rows": total, "rows_by_local_hour": by_hour}
            break
        out[key] = entry
    trades = {"files": 0, "rows": 0}
    for rel in src.trade_files(slug):
        with src.binary(rel) as raw:
            if raw is None:
                continue
            trades["rows"] += sum(1 for line in raw if line.strip())
        trades["files"] += 1
    out["execution_tape_trades"] = trades
    return out


def _copy_blob(src, bundle, digest, blobs):
    ref = allow.blob_ref(digest)
    rel = f"forecast_payload_cas/{ref}"
    with src.binary(rel) as raw:
        if raw is None:
            blobs["missing"] += 1
            return
        with bundle.file(rel, rel, src, rows_kind=False) as out:
            for chunk in iter(lambda: raw.read(CHUNK), b""):
                out.write(chunk, row=False)
            if out.sha.hexdigest() != digest:
                out.discard = True
                blobs["hash_mismatch"] += 1
                return
    blobs["copied"] += 1


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _head(repo):
    """The host repository HEAD from ``.git`` (read only; None when it cannot be read)."""
    try:
        git = Path(repo) / ".git"
        if git.is_file():
            git = Path(git.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip())
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head
        ref = head[4:].strip()
        common = Path((git / "commondir").read_text(encoding="utf-8").strip()) if (git / "commondir").is_file() \
            else None
        for base in (git, (git / common) if common else None):
            if base is not None and (base / ref).is_file():
                return (base / ref).read_text(encoding="utf-8").strip()
        for base in (git, (git / common) if common else None):
            packed = base / "packed-refs" if base is not None else None
            if packed is not None and packed.is_file():
                for line in packed.read_text(encoding="utf-8").splitlines():
                    if line.endswith(" " + ref):
                        return line.split()[0]
    except (OSError, IndexError):
        return None
    return None


def export(*, day, data_root, out, now=None, repo=None, clock=time.time, coverage_counts=False):
    """Export one target date's bundle. Returns the manifest.

    ``coverage_counts`` (OFF by default; each use needs master's ruling first) additionally opens the order-book,
    websocket, execution-tape files and the ``market_yes`` column to write integer counts. Without it only the
    section 9.1 inputs are opened.
    """
    check_date(day, now)
    src = Source(data_root, clock=clock, coverage_counts=coverage_counts)
    out = Path(out).resolve()
    data_root = Path(data_root).resolve()
    for forbidden_root in (data_root / "snapshots", data_root / "forecast_payload_cas"):
        if out == forbidden_root or forbidden_root in out.parents:
            raise ExportRefused(f"output {out} is inside the capture tree {forbidden_root}")
    final, staging = out / day.isoformat(), out / f".{day.isoformat()}.partial"
    sums = out / f"{day.isoformat()}{SUMS_SUFFIX}"
    if final.exists() or sums.exists():
        raise ExportRefused(f"{final} already exists: one export per date (move it aside for the re-export)")
    if staging.exists():
        raise ExportRefused(f"{staging} exists from an earlier failed run; inspect and remove it")
    started = datetime.now(timezone.utc)
    cut = allow.export_cut_utc(day)
    staging.mkdir(parents=True)
    try:
        bundle = Bundle(staging, day)
        counts, refs = {"dropped_after_cut": 0, "nbm_bad_ref": 0}, {}
        markets, price_cov, books = {}, {}, {}
        for market in allow.MARKETS:
            present, reason, market_refs, price = _project_market(src, bundle, market, day, cut, counts)
            markets[market] = {"expected": True, "present": present, "reason": reason}
            refs.update(market_refs)
            if src.coverage_counts:
                price_cov[market] = price
                books[market] = book_coverage(src, market, day)
        blobs = {"referenced": len(refs), "copied": 0, "missing": 0, "hash_mismatch": 0}
        for digest in sorted(refs):
            _copy_blob(src, bundle, digest, blobs)
        entries = [bundle.entries[rel] for rel in sorted(bundle.entries)]
        repo = Path(repo) if repo else Path(__file__).resolve().parents[3]
        manifest = {
            "schema": allow.BUNDLE_SCHEMA, "exporter_schema": SCHEMA, "target_date": day.isoformat(),
            "export_cut_utc": cut.isoformat(), "export_started_utc": started.isoformat(),
            "allowlist_sha256": allow.allowlist_sha256(),
            "exporter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "host_repo_head": _head(repo), "files": entries, "markets": markets, "nbm_blobs": blobs,
            "dropped_after_cut": counts["dropped_after_cut"], "nbm_rows_bad_ref": counts["nbm_bad_ref"],
            "min_quiet_seconds": MIN_QUIET_SECONDS, "read_mode": "bounded_range_at_open",
            "coverage_counts": src.coverage_counts,
            "export_finished_utc": datetime.now(timezone.utc).isoformat(),
        }
        if src.coverage_counts:
            manifest["market_price_coverage"] = {"hours_local": list(COVERAGE_HOURS), "counts_only": True,
                                                 "markets": price_cov}
            manifest["book_coverage"] = {"counts_only": True, "markets": books}
        body = json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8")
        (staging / allow.MANIFEST).write_bytes(body)
        # The ready marker, last. Bytes, not text mode: LF on every host (Windows text mode writes CRLF).
        (staging / allow.MANIFEST_SHA).write_bytes((_sha(body) + "\n").encode("ascii"))
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)  # only this run's own staging folder
        raise
    os.replace(staging, final)
    lines = [f"{_sha((final / allow.MANIFEST).read_bytes())}  {day.isoformat()}/{allow.MANIFEST}",
             f"{_sha((final / allow.MANIFEST_SHA).read_bytes())}  {day.isoformat()}/{allow.MANIFEST_SHA}"]
    lines += [f"{e['sha256']}  {day.isoformat()}/{e['path']}" for e in entries]
    sums.write_bytes(("\n".join(sorted(lines, key=lambda s: s.split("  ", 1)[1])) + "\n").encode("utf-8"))
    return manifest


# ----------------------------------------------------------------------------- CLI

def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.mg2_input_export")
    parser.add_argument("--date", action="append", required=True, help="target date D (repeatable)")
    repo = Path(__file__).resolve().parents[3]
    parser.add_argument("--data-root", default=str(repo / "data"))
    parser.add_argument("--out", default=str(repo / "data" / "exports" / "mg2-inputs"))
    parser.add_argument("--coverage-counts", action="store_true",
                        help="OFF by default. Also open order-book, websocket and execution-tape files and the "
                             "market_yes column to write integer coverage counts (B-1/PT-1). These are outside the "
                             "binding plan section 9.1 inputs: each use needs master's ruling first, and the "
                             "scheduled WeatherMg2InputExport task never sets it.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    days = [date.fromisoformat(d) for d in args.date]
    status = 0
    for day in days:
        try:
            manifest = export(day=day, data_root=args.data_root, out=args.out,
                              coverage_counts=args.coverage_counts)
        except FileTooFresh as exc:
            print(json.dumps({"target_date": day.isoformat(), "status": "too_fresh", "reason": str(exc)}))
            status = max(status, 3)
            continue
        except ExportRefused as exc:
            print(json.dumps({"target_date": day.isoformat(), "status": "refused", "reason": str(exc)}))
            status = max(status, 2)
            continue
        absent = sorted(m for m, v in manifest["markets"].items() if not v["present"])
        print(json.dumps({"target_date": day.isoformat(), "status": "exported" if not absent else "incomplete",
                          "absent_markets": absent, "files": len(manifest["files"]),
                          "nbm_blobs": manifest["nbm_blobs"],
                          "manifest_sha256": hashlib.sha256(
                              (Path(args.out) / day.isoformat() / allow.MANIFEST).read_bytes()).hexdigest()}))
        blobs = manifest["nbm_blobs"]
        if absent or blobs["missing"] or blobs["hash_mismatch"] or manifest["nbm_rows_bad_ref"]:
            status = max(status, 3)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
