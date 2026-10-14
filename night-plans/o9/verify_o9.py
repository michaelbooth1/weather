"""Read-only workstation verifier for the O9 book-summary inbox (plan section 9).

Run on the 32 GB workstation after the scp pull, before anything reads the summaries:

    python -I -B verify_o9.py --inbox <data\\research_inbox\\o9-book-summaries> \\
        --expected-manifest-sha256 <64 hex relayed by master out of band> [--sample-tgz <mi-books-sample.tgz>]

It writes nothing. It prints one receipt JSON object to stdout.
Exit codes: 0 PASS, 2 REFUSED (first failing check named in "refusal"), 3 ERROR.

Checks, in order:
 1. --expected-manifest-sha256 is given and is 64 hex characters (argparse refuses without it).
 2. sha256(MANIFEST.json bytes) equals it; the same bytes are then parsed (no second read).
 3. Manifest schema, the literal DATES/MARKETS, cutoff fields, and the 552-folder list match this file.
 4. The inbox holds exactly MANIFEST.json, SHA256SUMS and the staged files the manifest lists; every
    staged path names an allowlisted folder dated before 2026-09-30.
 5. SHA256SUMS hashes to the manifest's value and lists exactly the staged files with their hashes.
 6. Each staged file: stored bytes/sha256, gzip decode, decoded bytes/sha256, header sha256, row count,
    the row cutoff re-applied (any row at or after 2026-09-30T00:00:00Z refuses; counted, never shown),
    and the kept min/max timestamps.
 7. Optional, informational: members of the 79a sample tgz that name an allowlisted, staged folder are
    hashed and compared with the manifest's source identity for that folder (match/mismatch counts; a
    mismatch does not change the exit code). Out-of-scope members are skipped without hashing.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import zlib

SCHEMA_MANIFEST = "o9_book_summary_transfer.v1"
CUTOFF_UTC = dt.datetime(2026, 9, 30, tzinfo=dt.timezone.utc)
CUTOFF_ISO = "2026-09-30T00:00:00Z"
CUTOFF_DATE = "2026-09-30"
CUTOFF_EPOCH_MS = 1790726400000
GZ_NAME = "order_books_summary.csv.gz"
SUMMARY_NAME = "order_books_summary.csv"

MARKETS = (
    "atlanta", "austin", "chicago", "dallas", "denver", "houston",
    "los-angeles", "miami", "nyc", "san-francisco", "seattle", "toronto",
)

DATES = (
    "2026-08-15", "2026-08-16", "2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20",
    "2026-08-21", "2026-08-22", "2026-08-23", "2026-08-24", "2026-08-25", "2026-08-26",
    "2026-08-27", "2026-08-28", "2026-08-29", "2026-08-30", "2026-08-31",
    "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05", "2026-09-06",
    "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-12",
    "2026-09-13", "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
    "2026-09-19", "2026-09-20", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24",
    "2026-09-25", "2026-09-26", "2026-09-27", "2026-09-28", "2026-09-29",
)

MONTH_NAMES = {8: "august", 9: "september"}
MONTHS = {"august": 8, "september": 9}
ALLOWLIST_SLUGS = tuple(
    f"highest-temperature-in-{market}-on-{MONTH_NAMES[int(day[5:7])]}-{int(day[8:])}-2026"
    for day in DATES for market in MARKETS
)
ALLOWLIST_SHA256 = hashlib.sha256(("\n".join(ALLOWLIST_SLUGS) + "\n").encode("ascii")).hexdigest()

SLUG_RE = re.compile(
    r"^highest-temperature-in-(" + "|".join(re.escape(m) for m in MARKETS) + r")"
    r"-on-(august|september)-(\d{1,2})-(2026)$"
)
STAGED_PATH_RE = re.compile(r"^books/([a-z0-9-]+)/order_books_summary\.csv\.gz$")
SUMS_LINE_RE = re.compile(r"^([0-9a-f]{64})  (books/[a-z0-9-]+/order_books_summary\.csv\.gz)$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$")
EPOCH_MS_RE = re.compile(r"^\d{1,16}$")
REQUIRED_COLUMNS = ("captured_at_utc", "captured_at_local", "event_slug", "book_time_utc", "book_timestamp")
READ_CHUNK = 1024 * 1024

EXIT_OK, EXIT_REFUSED, EXIT_ERROR = 0, 2, 3


class Refusal(Exception):
    def __init__(self, code, **context):
        super().__init__(code)
        self.code = code
        self.context = context


def slug_date(slug):
    match = SLUG_RE.match(slug)
    if not match:
        return None
    return dt.date(int(match.group(4)), MONTHS[match.group(2)], int(match.group(3))).isoformat()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(READ_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fmt_utc(value):
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ---- Row rules: identical to o9_stage.py (any change must be made in both) -------------------

def parse_iso(text):
    if not ISO_RE.match(text):
        return None
    try:
        value = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo is not None else None


def parse_header(line):
    raw = line[3:] if line.startswith(b"\xef\xbb\xbf") else line
    text = raw.decode("latin-1").rstrip("\r\n")
    try:
        names = next(csv.reader([text], strict=True))
    except (csv.Error, StopIteration):
        raise Refusal("o9_header_unparseable")
    index = {}
    for column in REQUIRED_COLUMNS:
        if names.count(column) != 1:
            raise Refusal("o9_header_missing_or_duplicate", column=column)
        index[column] = names.index(column)
    return len(names), index


def classify_row(line, ncols, index, folder_slug):
    text = line.decode("latin-1").rstrip("\r\n")
    try:
        fields = next(csv.reader([text], strict=True))
    except (csv.Error, StopIteration):
        return "unparseable", None, None
    if len(fields) != ncols:
        return "unparseable", None, None
    if fields[index["event_slug"]] != folder_slug:
        return "slug_mismatch", None, None

    unparseable = False
    after = False

    captured = parse_iso(fields[index["captured_at_utc"]])
    if captured is None:
        unparseable = True
    elif captured >= CUTOFF_UTC:
        after = True

    local_text = fields[index["captured_at_local"]]
    local = parse_iso(local_text)
    if local is None:
        unparseable = True
    elif local >= CUTOFF_UTC or local_text[:10] >= CUTOFF_DATE:
        after = True

    book_text = fields[index["book_time_utc"]]
    book = None
    if book_text:
        book = parse_iso(book_text)
        if book is None:
            unparseable = True
        elif book >= CUTOFF_UTC:
            after = True

    stamp_text = fields[index["book_timestamp"]]
    if stamp_text:
        if not EPOCH_MS_RE.match(stamp_text):
            unparseable = True
        elif int(stamp_text) >= CUTOFF_EPOCH_MS:
            after = True

    if after:
        return "ge_cutoff", None, None
    if unparseable:
        return "unparseable", None, None
    return "keep", captured, book

# ---- end of shared row rules ------------------------------------------------------------------


def check_one(inbox, record):
    """Re-derive one staged file's identity and content bounds. Raises Refusal on the first problem."""
    slug = record["slug"]
    path = os.path.join(inbox, *record["staged_relpath"].split("/"))
    if os.path.getsize(path) != record["staged_bytes"] or sha256_file(path) != record["staged_sha256"]:
        raise Refusal("o9_staged_hash_mismatch", slug=slug)
    decoded = hashlib.sha256()
    decoded_bytes = 0
    rows = ge_cutoff = unparseable = 0
    kept_min = kept_max = book_max = None
    try:
        with gzip.open(path, "rb") as stream:
            header = stream.readline()
            if not header.endswith(b"\n"):
                raise Refusal("o9_truncated_line", slug=slug)
            ncols, index = parse_header(header)
            decoded.update(header)
            decoded_bytes += len(header)
            if hashlib.sha256(header).hexdigest() != record["header_sha256"]:
                raise Refusal("o9_header_sha_mismatch", slug=slug)
            for line in stream:
                decoded.update(line)
                decoded_bytes += len(line)
                if not line.endswith(b"\n"):
                    raise Refusal("o9_truncated_line", slug=slug)
                rows += 1
                kind, captured, book = classify_row(line, ncols, index, slug)
                if kind == "ge_cutoff":
                    ge_cutoff += 1
                elif kind == "unparseable":
                    unparseable += 1
                elif kind == "slug_mismatch":
                    raise Refusal("o9_event_slug_mismatch", slug=slug)
                else:
                    kept_min = captured if kept_min is None or captured < kept_min else kept_min
                    kept_max = captured if kept_max is None or captured > kept_max else kept_max
                    if book is not None and (book_max is None or book > book_max):
                        book_max = book
    except (EOFError, gzip.BadGzipFile, zlib.error):
        raise Refusal("o9_gzip_corrupt", slug=slug)
    if ge_cutoff:
        raise Refusal("o9_content_after_cutoff", slug=slug, rows=ge_cutoff)  # count only
    if unparseable:
        raise Refusal("o9_unparseable_rows", slug=slug, rows=unparseable)
    if decoded.hexdigest() != record["decoded_sha256"] or decoded_bytes != record["decoded_bytes"]:
        raise Refusal("o9_decoded_hash_mismatch", slug=slug)
    if rows != record["rows_kept"]:
        raise Refusal("o9_row_count_mismatch", slug=slug)
    derived = {
        "kept_captured_at_utc_min": fmt_utc(kept_min) if kept_min else None,
        "kept_captured_at_utc_max": fmt_utc(kept_max) if kept_max else None,
        "kept_book_time_utc_max": fmt_utc(book_max) if book_max else None,
    }
    for key, value in derived.items():
        if value != record[key]:
            raise Refusal("o9_bounds_mismatch", slug=slug, field=key)
    if derived["kept_captured_at_utc_max"] and derived["kept_captured_at_utc_max"] >= CUTOFF_ISO[:19]:
        raise Refusal("o9_content_after_cutoff", slug=slug)
    return rows, decoded_bytes


def check_manifest_header(manifest):
    if manifest.get("schema") != SCHEMA_MANIFEST:
        raise Refusal("o9_manifest_schema")
    if manifest.get("dates") != list(DATES) or manifest.get("markets") != list(MARKETS):
        raise Refusal("o9_manifest_scope_mismatch")
    if manifest.get("cutoff_utc") != CUTOFF_ISO or manifest.get("cutoff_epoch_ms") != CUTOFF_EPOCH_MS:
        raise Refusal("o9_manifest_cutoff_mismatch")
    if manifest.get("allowlist_sha256") != ALLOWLIST_SHA256:
        raise Refusal("o9_manifest_allowlist_mismatch")
    files = manifest.get("files")
    if not isinstance(files, list) or [f.get("slug") for f in files] != list(ALLOWLIST_SLUGS):
        raise Refusal("o9_manifest_file_list_mismatch")
    for record in files:
        day = slug_date(record["slug"])
        if day is None or day >= CUTOFF_DATE:
            raise Refusal("o9_name_date_refused", slug=record["slug"])
        if record["status"] == "staged":
            match = STAGED_PATH_RE.match(record.get("staged_relpath", ""))
            if not match or match.group(1) != record["slug"]:
                raise Refusal("o9_staged_path_invalid", slug=record["slug"])
            for key in ("staged_sha256", "decoded_sha256", "header_sha256"):
                if not HEX64_RE.match(str(record.get(key, ""))):
                    raise Refusal("o9_manifest_field_invalid", slug=record["slug"], field=key)
    return [f for f in files if f["status"] == "staged"]


def check_file_set(inbox, staged):
    expected = {"MANIFEST.json", "SHA256SUMS"} | {r["staged_relpath"] for r in staged}
    found = set()
    for root, _dirs, names in os.walk(inbox):
        for name in names:
            found.add(os.path.relpath(os.path.join(root, name), inbox).replace(os.sep, "/"))
    for rel in sorted(found):
        match = STAGED_PATH_RE.match(rel)
        if match:
            day = slug_date(match.group(1))
            if day is None or day >= CUTOFF_DATE:
                raise Refusal("o9_name_date_refused", path=rel)
    extra = sorted(found - expected)
    if extra:
        raise Refusal("o9_unlisted_file", count=len(extra), first=extra[0])
    missing = sorted(expected - found)
    if missing:
        raise Refusal("o9_missing_file", count=len(missing), first=missing[0])


def check_sums(inbox, manifest, staged):
    path = os.path.join(inbox, "SHA256SUMS")
    with open(path, "rb") as handle:
        data = handle.read()
    if hashlib.sha256(data).hexdigest() != manifest.get("sha256sums_sha256"):
        raise Refusal("o9_sha256sums_hash_mismatch")
    listed = {}
    for line in data.decode("ascii").splitlines():
        match = SUMS_LINE_RE.match(line)
        if not match or match.group(2) in listed:
            raise Refusal("o9_sha256sums_line_invalid")
        listed[match.group(2)] = match.group(1)
    if listed != {r["staged_relpath"]: r["staged_sha256"] for r in staged}:
        raise Refusal("o9_sha256sums_manifest_mismatch")


def check_sample_tgz(path, manifest):
    """Compare 79a sample members with the manifest's source identity. Only allowlisted members are hashed."""
    by_slug = {f["slug"]: f for f in manifest["files"] if f["status"] == "staged"}
    matched, mismatched, absent = 0, [], 0
    with tarfile.open(path, mode="r|gz") as archive:
        for member in archive:
            if not member.isfile():
                continue
            parts = member.name.replace("\\", "/").split("/")
            if len(parts) < 2 or parts[-1] != SUMMARY_NAME:
                continue
            slug = parts[-2]
            day = slug_date(slug)
            if day is None or day >= CUTOFF_DATE or slug not in by_slug:
                absent += 1
                continue  # not read: streaming skips the member's bytes without hashing them
            record = by_slug[slug]
            expected = record.get("source_decoded_sha256") or record.get("source_sha256")
            digest = hashlib.sha256()
            stream = archive.extractfile(member)
            for chunk in iter(lambda: stream.read(READ_CHUNK), b""):
                digest.update(chunk)
            if digest.hexdigest() == expected:
                matched += 1
            else:
                mismatched.append(slug)
    # Informational (plan section 9 step 7): a mismatch means the host file changed after the 79a pull; it is
    # reported to master, not refused.
    return {"sample_members_matched": matched, "sample_members_mismatched": len(mismatched),
            "sample_mismatched_slugs": mismatched, "sample_members_not_in_scope_or_not_staged": absent}


def verify(args):
    receipt = {"kind": "verify_o9", "inbox": os.path.abspath(args.inbox),
               "verifier_sha256": sha256_file(os.path.abspath(__file__)),
               "expected_manifest_sha256": args.expected_manifest_sha256}
    if not HEX64_RE.match(args.expected_manifest_sha256):
        raise Refusal("o9_expected_sha_not_64_lower_hex")
    with open(os.path.join(args.inbox, "MANIFEST.json"), "rb") as handle:
        manifest_bytes = handle.read()
    actual = hashlib.sha256(manifest_bytes).hexdigest()
    receipt["manifest_sha256"] = actual
    if actual != args.expected_manifest_sha256:
        raise Refusal("o9_manifest_sha_mismatch")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    staged = check_manifest_header(manifest)
    check_file_set(args.inbox, staged)
    check_sums(args.inbox, manifest, staged)
    total_rows = total_decoded = 0
    for record in staged:
        rows, decoded_bytes = check_one(args.inbox, record)
        total_rows += rows
        total_decoded += decoded_bytes
    totals = manifest.get("totals", {})
    if totals.get("rows_kept") != total_rows or totals.get("decoded_bytes") != total_decoded:
        raise Refusal("o9_manifest_totals_mismatch")
    receipt.update({
        "files_staged": len(staged),
        "counts": manifest.get("counts"),
        "rows_kept": total_rows,
        "decoded_bytes": total_decoded,
        "rows_dropped_ge_cutoff_on_host": totals.get("rows_dropped_ge_cutoff"),
        "rows_dropped_unparseable_on_host": totals.get("rows_dropped_unparseable"),
    })
    if args.sample_tgz:
        receipt.update(check_sample_tgz(args.sample_tgz, manifest))
    receipt["outcome"] = "PASS"
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only verifier for the O9 book-summary inbox.")
    parser.add_argument("--inbox", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True,
                        help="64 hex; relayed by master out of band, never read from the inbox")
    parser.add_argument("--sample-tgz", default=None, help="optional 79a mi-books-sample.tgz cross-check")
    args = parser.parse_args(argv)
    try:
        receipt = verify(args)
        code = EXIT_OK
    except Refusal as exc:
        receipt = {"kind": "verify_o9", "outcome": "REFUSED", "refusal": exc.code, **exc.context}
        code = EXIT_REFUSED
    except Exception as exc:  # noqa: BLE001 - report and exit non-zero
        receipt = {"kind": "verify_o9", "outcome": "ERROR", "error": type(exc).__name__, "detail": str(exc)[:300]}
        code = EXIT_ERROR
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
