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
* **Shared-read opens.** On Windows every read handle allows read, write and delete sharing, so a capture
  writer can append to, rename or delete a file the exporter is reading. Each file is read whole and closed at
  once, so the handle is held only for the read itself.
* **Dates.** A target date D is exported only if D <= 2026-09-29 (the development window) or D >= D0
  (2026-10-28; the MG-2 reservation exemption, option 2), and only after D's export cut has passed.
* **Projection, not copy.** Every record goes through the allow-list's projections; only rows captured at or
  before the export cut travel. NBM blobs are copied byte for byte after re-hashing.
* **Counts only.** ``market_price_coverage`` (B-1 section 3: per market, D's local 07-16 snapshots and how many
  carry a capture-time price on every band) and ``book_coverage`` (PT-1: rows of ``order_books_summary.csv``
  (or ``.csv.gz``) and ``market_ws_events.csv`` by local hour of D, and ``execution_tape\trades-*.jsonl`` line
  counts) are integers in the manifest. No price, book or trade value is written.

Output: ``<out>\<D>\`` (the bundle; ``manifest.json.sha256`` written last, then the folder is published by an
atomic rename from ``<out>\.<D>.partial``) and ``<out>\<D>.SHA256SUMS`` beside it (outside the bundle, which
must hold only allow-listed paths).

    python -m weather.calibration.mg2_input_export --date 2026-09-29 [--date ...] [--data-root <repo>\data]
        [--out <repo>\data\exports\mg2-inputs]
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
import stat
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.calibration import mg2_input_allowlist as allow

SCHEMA = "mg2_input_export/1"
DEV_LAST = date(2026, 9, 29)
FORWARD_FIRST = date(2026, 10, 28)  # MG-2 D0: option 2 exempts MG-2's dates from here
SUMS_SUFFIX = ".SHA256SUMS"
COVERAGE_HOURS = (7, 16)
TZ = {"atlanta": "America/New_York", "austin": "America/Chicago", "chicago": "America/Chicago",
      "dallas": "America/Chicago", "denver": "America/Denver", "houston": "America/Chicago",
      "los-angeles": "America/Los_Angeles", "miami": "America/New_York", "nyc": "America/New_York",
      "san-francisco": "America/Los_Angeles", "seattle": "America/Los_Angeles"}
# Every file this exporter may open, relative to the data root (posix). Nothing else is ever opened.
SOURCE_PATTERNS = (
    re.compile(r"^snapshots/(?P<slug>[a-z0-9-]+)/(?P<name>replay_inputs\.jsonl|snapshots_long\.csv|"
               r"features_long\.csv|forecast_payloads\.jsonl|forecast_payloads_long\.csv|"
               r"order_books_summary\.csv|order_books_summary\.csv\.gz|market_ws_events\.csv)$"),
    re.compile(r"^snapshots/(?P<slug>[a-z0-9-]+)/execution_tape/trades-\d{5}\.jsonl$"),
    re.compile(r"^forecast_payload_cas/sha256/[0-9a-f]{2}/[0-9a-f]{64}\.blob$"),
)
PRICE_COLUMN = "market_yes"  # read only to count presence; the value is never kept or written


class ExportRefused(RuntimeError):
    """The export cannot run (date, path, link or output); nothing is published."""


# ----------------------------------------------------------------------------- reading

def _share_all_open(path):
    """A binary read handle that lets writers append, replace or delete the file (Windows); plain elsewhere."""
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


class Source:
    """The host data root; every open goes through ``open``, which admits only ``SOURCE_PATTERNS``."""

    def __init__(self, root):
        root = Path(root)
        if not root.is_absolute() or not root.is_dir() or not (root / "snapshots").is_dir():
            raise ExportRefused(f"data root {root} is not an absolute directory with snapshots/")
        self.root = root
        self.opened = []

    def known(self, rel):
        """A listed file name, in one of the 11 markets' event folders or the shared NBM store."""
        for pattern in SOURCE_PATTERNS:
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

    def read(self, rel):
        """``(bytes, size, mtime_utc)`` of a known file, or None when absent."""
        full = self.path(rel)
        if full is None:
            return None
        with _share_all_open(full) as handle:
            data = handle.read()
        self.opened.append(rel)
        mtime = datetime.fromtimestamp(os.stat(full).st_mtime, timezone.utc).isoformat()
        return data, len(data), mtime, rel

    @contextlib.contextmanager
    def lines(self, rel):
        """Text lines of a known file (``.gz`` decompressed), streamed; yields None when absent."""
        full = self.path(rel)
        if full is None:
            yield None
            return
        self.opened.append(rel)
        with _share_all_open(full) as raw:
            stream = gzip.GzipFile(fileobj=raw, mode="rb") if rel.endswith(".gz") else raw
            with io.TextIOWrapper(stream, encoding="utf-8", newline="") as text:
                yield text

    def is_cold_archived(self, slug):
        """True when the folder carries the cold-archive marker (existence check only; nothing opened)."""
        return os.path.lexists(self.root / "snapshots" / slug / ".cold_archive")

    def trade_files(self, slug):
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


def parse_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _jsonl(data):
    return [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]


def _csv_rows(data):
    reader = csv.DictReader(io.StringIO(data.decode("utf-8"), newline=""))
    return list(reader)


def _jsonl_bytes(records):
    return "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in records).encode("utf-8")


def _csv_bytes(rows, fields):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(fields), lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in fields})
    return out.getvalue().encode("utf-8")


# ----------------------------------------------------------------------------- dates

def check_date(day, now=None):
    """D <= 2026-09-29 or D >= D0 (option 2), and D's export cut has passed."""
    if DEV_LAST < day < FORWARD_FIRST:
        raise ExportRefused(f"{day} is after {DEV_LAST} and before MG-2's D0 {FORWARD_FIRST}: refused")
    now = now or datetime.now(timezone.utc)
    if now <= allow.export_cut_utc(day):
        raise ExportRefused(f"{day}'s export cut {allow.export_cut_utc(day).isoformat()} has not passed")


# ----------------------------------------------------------------------------- one bundle

def _local(market, captured):
    return captured.astimezone(ZoneInfo(TZ[market]))


def _in_cut(record, cut):
    captured = parse_time(record.get("captured_at_utc"))
    return captured is not None and captured <= cut


def _project_market(src, market, day, cut, files, counts):
    """The D, D-1 and D+1 files of one market. Returns ``(present, reason, nbm_refs)``."""
    slug = allow.slug_for(market, day)
    reason, refs = None, {}
    # F1 replay inputs (D)
    got = src.read(f"snapshots/{slug}/replay_inputs.jsonl")
    if got is None:
        reason = "cold_archived_restore_first" if src.is_cold_archived(slug) else "replay_inputs_missing"
    else:
        records = _jsonl(got[0])
        kept = [allow.project_replay_record(r) for r in records if _in_cut(r, cut)]
        counts["dropped_after_cut"] += len(records) - len(kept)
        if not kept:
            reason = "no_replay_inputs_before_cut"
        else:
            files[f"snapshots/{slug}/replay_inputs.jsonl"] = (_jsonl_bytes(kept), len(kept), got)
    # F2, F3 (D)
    for name in ("snapshots_long.csv", "features_long.csv"):
        got = src.read(f"snapshots/{slug}/{name}")
        if got is None:
            reason = reason or f"{name}_missing"
            continue
        rows = _csv_rows(got[0])
        kept = [r for r in rows if _in_cut(r, cut)]
        counts["dropped_after_cut"] += len(rows) - len(kept)
        files[f"snapshots/{slug}/{name}"] = (_csv_bytes(kept, allow.CSV_FIELDS[name]), len(kept), got)
    # F1b: D-1's last snapshot, METAR rows only
    prev = allow.slug_for(market, day - timedelta(days=1))
    got = src.read(f"snapshots/{prev}/replay_inputs.jsonl")
    if got is not None:
        records = [r for r in _jsonl(got[0]) if _in_cut(r, cut)]
        if records:
            last = max(records, key=lambda r: parse_time(r.get("captured_at_utc")))
            files[f"prev_day/{prev}/metar_rows.jsonl"] = (_jsonl_bytes([allow.project_prev_day_record(last)]), 1,
                                                          got)
    # F4: NBM manifest rows of the D-1, D and D+1 folders (JSONL, else the long CSV)
    for offset in allow.PATHS["nbm_manifest"]["days"]:
        fslug = allow.slug_for(market, day + timedelta(days=offset))
        got = src.read(f"snapshots/{fslug}/forecast_payloads.jsonl")
        rows = _jsonl(got[0]) if got is not None else None
        if got is None:
            got = src.read(f"snapshots/{fslug}/forecast_payloads_long.csv")
            rows = _csv_rows(got[0]) if got is not None else None
        if got is None:
            continue
        kept = [allow.project_row(r, allow.NBM_FIELDS) for r in rows
                if r.get("source") == allow.NBM_SOURCE and _in_cut(r, cut)]
        for row in kept:
            digest = str(row.get("payload_hash") or "")
            if row.get("payload_storage_scope") == allow.NBM_SCOPE and row.get("payload_ref") == allow.blob_ref(
                    digest) and allow.BLOB_RE.match(str(row.get("payload_ref"))):
                refs[digest] = row["payload_ref"]
            elif row.get("payload_storage_scope") == allow.NBM_SCOPE:
                counts["nbm_bad_ref"] += 1
        files[f"snapshots/{fslug}/forecast_payloads.jsonl"] = (_jsonl_bytes(kept), len(kept), got)
    return reason is None, reason, refs


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


def market_price_coverage(src, market, day, cut):
    """B-1 section 3 counts: D's local 07-16 snapshots (captured by the cut) and those priced on every band."""
    got = src.read(f"snapshots/{allow.slug_for(market, day)}/snapshots_long.csv")
    if got is None:
        return {"snapshots_07_16": 0, "priced_07_16": 0, "source_present": False}
    snaps = {}
    for row in _csv_rows(got[0]):
        captured = parse_time(row.get("captured_at_utc"))
        if captured is None or captured > cut:
            continue
        local = _local(market, captured)
        if local.date() != day or not COVERAGE_HOURS[0] <= local.hour <= COVERAGE_HOURS[1]:
            continue
        value = str(row.get(PRICE_COLUMN) or "").strip()
        try:
            ok = value != "" and float(value) == float(value)
        except ValueError:
            ok = False
        sid = row.get("snapshot_id")
        snaps[sid] = snaps.get(sid, True) and ok
    return {"snapshots_07_16": len(snaps), "priced_07_16": sum(snaps.values()), "source_present": True}


def book_coverage(src, market, day):
    """PT-1 counts: order-book summary and market websocket rows by local hour of D; execution-tape trade lines."""
    slug = allow.slug_for(market, day)
    out = {}
    for key, names, column in (("order_books_summary", ("order_books_summary.csv", "order_books_summary.csv.gz"),
                                "captured_at_utc"),
                               ("market_ws_events", ("market_ws_events.csv",), "received_at_utc")):
        entry = {"present": False, "file": None, "rows": 0, "rows_by_local_hour": {}}
        for name in names:
            with src.lines(f"snapshots/{slug}/{name}") as lines:
                if lines is None:
                    continue
                total, by_hour = _hour_counts(lines, column, market, day)
            entry = {"present": True, "file": name, "rows": total, "rows_by_local_hour": by_hour}
            break
        out[key] = entry
    trades = {"files": 0, "rows": 0}
    for rel in src.trade_files(slug):
        with src.lines(rel) as lines:
            if lines is None:
                continue
            trades["rows"] += sum(1 for line in lines if line.strip())
        trades["files"] += 1
    out["execution_tape_trades"] = trades
    return out


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


def export(*, day, data_root, out, now=None, repo=None):
    """Export one target date's bundle. Returns the manifest."""
    check_date(day, now)
    src = Source(data_root)
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
    files, counts, refs = {}, {"dropped_after_cut": 0, "nbm_bad_ref": 0}, {}
    markets, price_cov, books = {}, {}, {}
    for market in allow.MARKETS:
        present, reason, market_refs = _project_market(src, market, day, cut, files, counts)
        markets[market] = {"expected": True, "present": present, "reason": reason}
        refs.update(market_refs)
        price_cov[market] = market_price_coverage(src, market, day, cut)
        books[market] = book_coverage(src, market, day)
    blobs = {"referenced": len(refs), "copied": 0, "missing": 0, "hash_mismatch": 0}
    for digest in sorted(refs):
        ref = allow.blob_ref(digest)
        got = src.read(f"forecast_payload_cas/{ref}")
        if got is None:
            blobs["missing"] += 1
            continue
        if _sha(got[0]) != digest:
            blobs["hash_mismatch"] += 1
            continue
        files[f"forecast_payload_cas/{ref}"] = (got[0], None, got)
        blobs["copied"] += 1

    entries = []
    for rel in sorted(files):
        data, rows, (_, source_bytes, source_mtime, source_rel) = files[rel]
        if allow.classify_path(rel, day) is None:
            raise ExportRefused(f"internal: {rel} is not an allow-listed bundle path")
        entries.append({"path": rel, "sha256": _sha(data), "bytes": len(data), "rows": rows,
                        "source_path": source_rel,
                        "source_bytes": source_bytes, "source_mtime_utc": source_mtime})
    repo = Path(repo) if repo else Path(__file__).resolve().parents[3]
    manifest = {
        "schema": allow.BUNDLE_SCHEMA, "exporter_schema": SCHEMA, "target_date": day.isoformat(),
        "export_cut_utc": cut.isoformat(), "export_started_utc": started.isoformat(),
        "allowlist_sha256": allow.allowlist_sha256(),
        "exporter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "host_repo_head": _head(repo), "files": entries, "markets": markets, "nbm_blobs": blobs,
        "dropped_after_cut": counts["dropped_after_cut"], "nbm_rows_bad_ref": counts["nbm_bad_ref"],
        "market_price_coverage": {"hours_local": list(COVERAGE_HOURS), "counts_only": True, "markets": price_cov},
        "book_coverage": {"counts_only": True, "markets": books},
    }
    staging.mkdir(parents=True)
    for rel, (data, _rows, _src) in files.items():
        target = staging.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest["export_finished_utc"] = datetime.now(timezone.utc).isoformat()
    body = json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8")
    (staging / allow.MANIFEST).write_bytes(body)
    (staging / allow.MANIFEST_SHA).write_text(_sha(body) + "\n", encoding="utf-8")  # the ready marker, last
    os.replace(staging, final)
    lines = [f"{_sha((final / allow.MANIFEST).read_bytes())}  {day.isoformat()}/{allow.MANIFEST}",
             f"{_sha((final / allow.MANIFEST_SHA).read_bytes())}  {day.isoformat()}/{allow.MANIFEST_SHA}"]
    lines += [f"{e['sha256']}  {day.isoformat()}/{e['path']}" for e in entries]
    sums.write_text("\n".join(sorted(lines, key=lambda s: s.split("  ", 1)[1])) + "\n", encoding="utf-8")
    return manifest


# ----------------------------------------------------------------------------- CLI

def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.mg2_input_export")
    parser.add_argument("--date", action="append", required=True, help="target date D (repeatable)")
    repo = Path(__file__).resolve().parents[3]
    parser.add_argument("--data-root", default=str(repo / "data"))
    parser.add_argument("--out", default=str(repo / "data" / "exports" / "mg2-inputs"))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    days = [date.fromisoformat(d) for d in args.date]
    status = 0
    for day in days:
        try:
            manifest = export(day=day, data_root=args.data_root, out=args.out)
        except ExportRefused as exc:
            print(json.dumps({"target_date": day.isoformat(), "status": "refused", "reason": str(exc)}))
            status = 2
            continue
        absent = sorted(m for m, v in manifest["markets"].items() if not v["present"])
        print(json.dumps({"target_date": day.isoformat(), "status": "exported" if not absent else "incomplete",
                          "absent_markets": absent, "files": len(manifest["files"]),
                          "nbm_blobs": manifest["nbm_blobs"],
                          "manifest_sha256": hashlib.sha256(
                              (Path(args.out) / day.isoformat() / allow.MANIFEST).read_bytes()).hexdigest()}))
        if absent or manifest["nbm_blobs"]["missing"] or manifest["nbm_blobs"]["hash_mismatch"] or                 manifest["nbm_rows_bad_ref"]:
            status = max(status, 3)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
