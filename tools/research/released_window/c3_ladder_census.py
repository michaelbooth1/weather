"""C3 ladder census: outcome-free coverage upper bound for the frozen T+1 fair-value scorer (R28b, lane L41).

Research tool on a run branch that is never merged (master ruling R28b, 2026-11-01). It answers one question
before any builder work: at how many (market, target, lead, UTC hour) cells did 88a capture, at ONE instant,
a books row that holds every band of the event, as the frozen scorer needs?

Frozen requirement (d937b34ab): ``maker_fair_value_score.py`` refuses an event-instant unless the captured book
set equals the event's bands and every band has a contemporaneous YES book with non-empty bids and asks
(``incomplete_captured_minute``, ``missing_contemporaneous_two_sided_mid``); ``maker_plugin_runner.py`` takes
the YES and NO books of each band from the newest capture at or before the instant (``captured_book``) and counts
the expected bands as active, not closed and ``enableOrderBook`` not false.

Cell rule (WS brief R28b step 2). A cell (market, target, lead, UTC hour) is COVERED if, at one books capture
instant in that hour, for EVERY band of the slug's latest discovery at or before the instant that is active,
not closed and has ``enableOrderBook`` not false:
  - the instant's books rows hold the band's YES and NO asset ids (and the book ``market`` is the band);
  - the YES book has a non-empty bid list and a non-empty ask list;
  - band rows for the slug (``snapshots_long.csv`` or the first ``clob_tokens.jsonl`` batch) exist at or before
    the instant.
Donor flag: a covered cell counts only if its (market, lead, local hour) has covered cells on >= 2 target dates.

This is an UPPER BOUND (method rule 2), not a rule-16 projection: fair-value availability, descriptors,
active intervals and partition checks are not evaluated.

Read discipline. Only ids, flags, list LENGTHS and timestamps are extracted. No price, size, label, settlement or
fair value is printed, stored or compared. ``settlements/``, forecasts, explanations and payload stores are never
opened. Scope is fixed: 88a UTC capture days 2026-09-25..2026-10-07 and local targets 2026-09-25..2026-10-08
minus Austin 2026-10-03 (released for C3 by the owner's 2026-10-30 release of 09-30..10-14, kill-only and atlas
reads). Anything at or after 2026-10-15 is refused outright.

Integrity runs first and refuses before any segment is parsed: the export's SHA256SUMS and receipt hashes are
pinned, every listed file is re-hashed and no unlisted file may exist; the prior C3 archive is re-hashed too.

    python -m tools.research.released_window.c3_ladder_census --export-root C:\\archive\\inputs\\export2-batch1-c3 \
        --prior-archive C:\\archive\\ruled-out\\c3-t1-fv-kill-tier --out C:\\t\\L41\\census_out
"""
from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import io
import json
import os
import platform
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from weather.market.market_registry import BUILTIN_SPECS

SCHEMA = "c3_ladder_census/1"
FIRST_DAY, LAST_DAY = date(2026, 9, 25), date(2026, 10, 7)
FIRST_TARGET, LAST_TARGET = date(2026, 9, 25), date(2026, 10, 8)
EMBARGO_FIRST = date(2026, 10, 15)
EXCLUDED_MARKET_DAYS = frozenset({("austin", date(2026, 10, 3))})
LEADS = (1, 2)
DONOR_MIN_DATES = 2
# Close rule, fixed by master ruling R28b (1) before the census runs.
CLOSE_MIN_EVENT_HOURS, CLOSE_MIN_TARGETS, CLOSE_MIN_MARKETS = 200, 10, 5

# Pinned integrity inputs (WS brief R28b step 1; full hashes of the prefixes the ruling names).
EXPORT_SUMS_SHA256 = "84a161601a6e90a3a3fd0a420ac4d071e78ad7ce8c795641c4e824c89a070c3c"
EXPORT_RECEIPT_SHA256 = "2d4c34b269e8b7c98f8c04fb912f737ef743f74753711512ca6629596d4562df"
EXPORT_FILE_COUNT = 136_445
PRIOR_SUMS_SHA256 = "4a8cde47b6ebfdb2543333f98f97c871b56afbe7e6cfad6045b558179046af3b"
PRIOR_FILE_COUNT = 21
PRIOR_LAUNCHER_RECEIPT = ("run/c3run_out/launcher_receipt.json",
                          "5716dee2429805db19e9372e46ab21b61195834bd6ec2befd68cf5abbcd8e636")
PRIOR_POSTRUN_LOG = ("run/postrun/c3_postrun_checks.log",
                     "5678037e3e1f0620122ffcef15856671950d392edaf87e87e15ab0100e81be0c")

SEGMENT_NAME = re.compile(r"(?:[01]\d|2[0-3])-[0-9a-f]{12}")
PUNCTUATION = re.compile(r"[\s\[\],]*")
HIST_EDGES = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


class Refused(RuntimeError):
    """Integrity or scope refusal: nothing is counted."""


# ----------------------------------------------------------------------------- small helpers

@lru_cache(maxsize=1 << 18)
def ts(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("naive_timestamp")
    return result.astimezone(timezone.utc)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha256_file(path, chunk=1 << 20):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def event_identity(slug):
    """Frozen ``maker_plugin.inputs.event_identity``: registered prefix + %B-%d-%Y."""
    for spec in BUILTIN_SPECS:
        prefix = spec.slug_prefix + "-"
        if slug.startswith(prefix):
            return spec, datetime.strptime(slug[len(prefix):], "%B-%d-%Y").date()
    raise ValueError("unregistered_event")


def in_scope(market_id, target):
    if target >= EMBARGO_FIRST:
        raise Refused(f"embargoed_target:{market_id}:{target}")
    return FIRST_TARGET <= target <= LAST_TARGET and (market_id, target) not in EXCLUDED_MARKET_DAYS


def read_maybe_gz(path):
    path = Path(path)
    if path.is_file():
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rb") as handle:
            return handle.read()
    alt = path.with_name(path.name + ".gz")
    if alt.is_file():
        with gzip.open(alt, "rb") as handle:
            return handle.read()
    return None


# ----------------------------------------------------------------------------- integrity

def parse_sums(raw):
    entries = {}
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        name = name.lstrip("*").strip().replace("\\", "/")
        if name in entries:
            raise Refused(f"duplicate_sums_entry:{name}")
        entries[name] = digest.lower()
    return entries


def verify_tree(root, sums_name, sums_sha, expected_count, extra_allowed=(), progress=None):
    """Re-hash every SUMS entry and refuse on any mismatch, missing file or unlisted file."""
    root = Path(root)
    sums_path = root / sums_name
    if not sums_path.is_file():
        raise Refused(f"missing_sums:{sums_path}")
    raw = sums_path.read_bytes()
    actual_sums = sha256_bytes(raw)
    if sums_sha is not None and actual_sums != sums_sha:
        raise Refused(f"sums_sha_mismatch:{sums_path}:{actual_sums}")
    entries = parse_sums(raw)
    if expected_count is not None and len(entries) != expected_count:
        raise Refused(f"sums_entry_count:{len(entries)}!={expected_count}")
    on_disk = set()
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            rel = (Path(dirpath) / name).relative_to(root).as_posix()
            on_disk.add(rel)
    allowed = {sums_name, *extra_allowed}
    extra = sorted(on_disk - set(entries) - allowed)
    missing = sorted(set(entries) - on_disk)
    if extra:
        raise Refused(f"unlisted_files:{len(extra)}:{extra[:3]}")
    if missing:
        raise Refused(f"missing_files:{len(missing)}:{missing[:3]}")
    for i, (rel, digest) in enumerate(sorted(entries.items())):
        actual = sha256_file(root / rel)
        if actual != digest:
            raise Refused(f"file_sha_mismatch:{rel}")
        if progress and i and i % 20000 == 0:
            progress(f"integrity {root.name}: {i}/{len(entries)}")
    return dict(root=str(root), sums_sha256=actual_sums, files_verified=len(entries), extra_files=0,
                missing_files=0, result="MATCH")


def verify_inputs(export_root, prior_archive, progress=None, pins=None):
    pins = pins or {}
    prior = verify_tree(prior_archive, "SHA256SUMS", pins.get("prior_sums", PRIOR_SUMS_SHA256),
                        pins.get("prior_count", PRIOR_FILE_COUNT), progress=progress)
    prior_entries = parse_sums((Path(prior_archive) / "SHA256SUMS").read_bytes())
    for rel, digest in pins.get("prior_named", (PRIOR_LAUNCHER_RECEIPT, PRIOR_POSTRUN_LOG)):
        if prior_entries.get(rel) != digest:
            raise Refused(f"prior_named_file:{rel}")
    receipt = Path(export_root) / "receipt.json"
    if not receipt.is_file():
        raise Refused("missing_export_receipt")
    receipt_sha = sha256_file(receipt)
    if receipt_sha != pins.get("export_receipt", EXPORT_RECEIPT_SHA256):
        raise Refused(f"export_receipt_sha_mismatch:{receipt_sha}")
    export = verify_tree(export_root, "SHA256SUMS", pins.get("export_sums", EXPORT_SUMS_SHA256),
                         pins.get("export_count", EXPORT_FILE_COUNT), extra_allowed=("receipt.json",),
                         progress=progress)
    export["receipt_sha256"] = receipt_sha
    return dict(prior_archive=prior, export=export)


# ----------------------------------------------------------------------------- sealed segment reading

class Segment:
    """Manifested files only; size, sha and offsets verified before any row is used."""

    def __init__(self, folder, manifest, counts):
        self.folder, self.manifest, self.counts = folder, manifest, counts
        self.cache = {}

    def rows(self, name):
        if name in self.cache:
            return self.cache[name]
        if name not in self.manifest["files"]:
            raise ValueError("reference_outside_manifest")
        expected = self.manifest["files"][name]
        raw = read_maybe_gz(self.folder / name)
        if raw is None:
            raise ValueError("manifested_file_missing")
        if len(raw) != expected["bytes"] or sha256_bytes(raw) != expected["sha256"]:
            raise ValueError("sealed_file_hash_or_size_mismatch")
        rows, offset = {}, 0
        for line in raw.splitlines(keepends=True):
            row = json.loads(line)
            if not line.endswith(b"\n") or row["offset"] != offset:
                raise ValueError("sealed_record_offset_or_newline")
            rows[offset] = row
            offset += len(line)
        if len(rows) != expected["records"]:
            raise ValueError("sealed_record_count_mismatch")
        self.cache[name] = rows
        self.counts["sealed_files_verified"] += 1
        return rows

    def target(self, ref, row):
        if not isinstance(ref.get("offset"), int) or ref["offset"] < 0:
            raise ValueError("payload_reference_offset")
        target = self.rows(ref["file"])[ref["offset"]]
        if target["sequence"] > row["sequence"]:
            raise ValueError("future_payload_reference")
        return target

    def payload(self, row, depth=0):
        """Frozen ``maker_plugin_capture.Segment.payload`` semantics."""
        if depth > 3:
            raise ValueError("payload_reference_cycle")
        if "payload_ref" in row:
            raw = self.payload(self.target(row["payload_ref"], row), depth + 1)
        elif "parts" in row:
            raw = b"".join(part["literal_utf8"].encode() if "literal_utf8" in part
                           else self.payload(self.target(part, row), depth + 1) for part in row["parts"])
        else:
            raw = row["body_utf8"].encode() if "body_utf8" in row else base64.b64decode(row["body_base64"],
                                                                                       validate=True)
        if "kind" in row:
            expected = row.get("stored_sha256", row["response_sha256"])
            if sha256_bytes(raw) != expected:
                canonical = sha256_bytes(encoded(json.loads(raw)))
                if row["body_stored"] or canonical != row.get("content_sha256"):
                    raise ValueError("payload_hash_mismatch")
            if row.get("content_sha256"):
                if sha256_bytes(encoded(json.loads(raw))) != row["content_sha256"]:
                    raise ValueError("payload_content_hash_mismatch")
        return raw


def book_summary(book):
    """Ids and list lengths only; the price levels themselves are never kept."""
    return (str(book["asset_id"]), str(book.get("market", "")).lower(),
            len(book.get("bids") or ()), len(book.get("asks") or ()))


class BooksDecoder:
    """Decode a books capture into {asset_id: (market, n_bids, n_asks)} with per-reference caching."""

    def __init__(self, segment):
        self.segment, self.ref_cache = segment, {}

    def ref_summary(self, ref, row):
        key = (ref["file"], ref["offset"])
        if key not in self.ref_cache:
            body = json.loads(self.segment.payload(self.segment.target(ref, row), 1))
            self.ref_cache[key] = [book_summary(b) for b in (body if isinstance(body, list) else [body])]
        return self.ref_cache[key]

    def decode(self, row):
        raw = self.segment.payload(row)  # verifies the whole-row hash first
        parts = row.get("parts")
        summaries = []
        if parts and all("literal_utf8" not in p or PUNCTUATION.fullmatch(p["literal_utf8"]) for p in parts):
            for part in parts:
                if "literal_utf8" not in part:
                    summaries.extend(self.ref_summary(part, row))
        else:
            payload = json.loads(raw)
            summaries = [book_summary(b) for b in payload]
        return summaries


def sealed_segments(day_root, counts):
    found = []
    if not day_root.is_dir():
        counts["segments.missing_date"] += 1
        return found
    for folder in sorted(day_root.iterdir()):
        if not SEGMENT_NAME.fullmatch(folder.name):
            continue
        raw = read_maybe_gz(folder / "manifest.json")
        if raw is None:
            counts["segments.unsealed_skipped"] += 1
            continue
        manifest = json.loads(raw)
        if manifest.get("schema_version") != "maker_evidence_v2":
            raise Refused(f"unsupported_seal_schema:{folder}")
        found.append((ts(manifest["sealed_at_utc"]), folder, manifest))
    return sorted(found, key=lambda item: (item[0], item[1].name))


# ----------------------------------------------------------------------------- band-row availability

def band_row_first_time(snapshot_root, slug, counts):
    """Earliest capture time of any band row for the slug: snapshots_long.csv or first clob_tokens batch.

    Only the ``captured_at_utc`` column is extracted; no other field is retained.
    """
    folder = snapshot_root / slug
    times = []
    raw = read_maybe_gz(folder / "snapshots_long.csv")
    if raw is not None:
        reader = csv.reader(io.StringIO(raw.decode("utf-8-sig")))
        header = next(reader, None)
        if header and "captured_at_utc" in header:
            col = header.index("captured_at_utc")
            for values in reader:
                if len(values) > col and values[col]:
                    try:
                        times.append(ts(values[col]))
                    except ValueError:
                        counts["band_rows.unparseable_time"] += 1
        counts["band_rows.snapshots_long_files"] += 1
    raw = read_maybe_gz(folder / "clob_tokens.jsonl")
    if raw is not None:
        for line in raw.splitlines():
            if line.strip():
                value = json.loads(line).get("captured_at_utc")
                if value:
                    times.append(ts(value))
                break  # first batch only, as the frozen token_bands reader
        counts["band_rows.clob_token_files"] += 1
    return min(times) if times else None


# ----------------------------------------------------------------------------- census

def band_tokens(band):
    tokens, outcomes = band.get("clobTokenIds"), band.get("outcomes")
    try:
        tokens = json.loads(tokens) if isinstance(tokens, str) else tokens
        outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
        if len(tokens) != 2 or len(outcomes) != 2 or set(outcomes) != {"Yes", "No"}:
            return None
        return str(tokens[outcomes.index("Yes")]), str(tokens[outcomes.index("No")])
    except (ValueError, TypeError, AttributeError):
        return None


def instant_fraction(event, books, band_ready):
    """Fraction of expected bands satisfied at this instant, plus the expected count and a reason."""
    expected = [b for b in event.get("markets", ())
                if b.get("active") and not b.get("closed") and b.get("enableOrderBook") is not False]
    if not expected:
        return 0.0, 0, "no_expected_bands"
    ok = 0
    reasons = Counter()
    for band in expected:
        pair = band_tokens(band)
        cid = str(band.get("conditionId", "")).lower()
        if pair is None:
            reasons["malformed_tokens"] += 1
            continue
        yes, no = books.get(pair[0]), books.get(pair[1])
        if yes is None or no is None:
            reasons["yes_or_no_book_absent"] += 1
            continue
        if yes[0] != cid or no[0] != cid:
            reasons["book_condition_mismatch"] += 1
            continue
        if yes[1] == 0 or yes[2] == 0:
            reasons["yes_side_empty"] += 1
            continue
        ok += 1
    reason = "covered" if ok == len(expected) and band_ready else (
        "band_rows_absent" if ok == len(expected) else reasons.most_common(1)[0][0])
    return ok / len(expected), len(expected), reason


def run_census(export_root, progress=None):
    data = Path(export_root) / "data"
    evidence, snapshots = data / "maker_evidence", data / "snapshots"
    counts = Counter()
    cells = {}
    band_first = {}
    instant_reasons = Counter()
    days = []
    day = FIRST_DAY
    while day <= LAST_DAY:
        days.append(day)
        day += timedelta(days=1)
    present = sorted(p.name for p in evidence.iterdir()) if evidence.is_dir() else []
    for name in present:
        if date.fromisoformat(name) >= EMBARGO_FIRST:
            raise Refused(f"embargoed_capture_day_present:{name}")
    for day in days:
        day_name = day.isoformat()
        for sealed, folder, manifest in sealed_segments(evidence / day_name, counts):
            counts["segments"] += 1
            segment = Segment(folder, manifest, counts)
            files = manifest["files"]
            discovery = []
            if "discovery.jsonl" in files:
                for row in segment.rows("discovery.jsonl").values():
                    if row.get("kind") != "discovery" or row.get("http_status") != 200:
                        counts["discovery.skipped_non_200"] += 1
                        continue
                    at = ts(row["captured_at_utc"])
                    events = json.loads(segment.payload(row))
                    discovery.append((at, row["sequence"], events))
            discovery.sort(key=lambda item: (item[0], item[1]))
            instants = defaultdict(dict)
            if "books.jsonl" in files:
                decoder = BooksDecoder(segment)
                for row in segment.rows("books.jsonl").values():
                    if row.get("kind") != "books" or row.get("http_status") != 200:
                        counts["books.skipped_non_200"] += 1
                        continue
                    at = ts(row["captured_at_utc"])
                    if at.date() != day or at > sealed:
                        counts["books.outside_segment_day"] += 1
                        continue
                    counts["books.captures"] += 1
                    for asset, market, nb, na in decoder.decode(row):
                        prior = instants[at].get(asset)
                        # Same-instant duplicates: keep the most permissive (upper bound).
                        if prior is None or (prior[1] > 0 and prior[2] > 0) < (nb > 0 and na > 0):
                            instants[at][asset] = (market, nb, na)
            latest, cursor = {}, 0
            for at in sorted(instants):
                books = instants[at]
                counts["instants"] += 1
                # Latest discovery per slug at or before the instant (segment-local, as the frozen builder).
                while cursor < len(discovery) and discovery[cursor][0] <= at:
                    for event in discovery[cursor][2]:
                        latest[event["slug"]] = event  # a later capture at the same clock overrides
                    cursor += 1
                for slug, event in sorted(latest.items()):
                    try:
                        spec, target = event_identity(slug)
                    except ValueError:
                        counts["events.unregistered"] += 1
                        continue
                    local = at.astimezone(spec.tz)
                    lead = (target - local.date()).days
                    if lead not in LEADS:
                        continue
                    if not in_scope(spec.id, target):
                        counts["events.out_of_scope"] += 1
                        continue
                    if slug not in band_first:
                        band_first[slug] = band_row_first_time(snapshots, slug, counts)
                    first = band_first[slug]
                    band_ready = first is not None and first <= at
                    fraction, expected, reason = instant_fraction(event, books, band_ready)
                    instant_reasons[(lead, reason)] += 1
                    hour = at.replace(minute=0, second=0, microsecond=0)
                    key = (spec.id, target.isoformat(), lead, hour.isoformat())
                    cell = cells.get(key)
                    if cell is None:
                        cell = cells[key] = dict(market=spec.id, target=target.isoformat(), lead=lead,
                                                 utc_hour=hour.isoformat(),
                                                 local_hour=hour.astimezone(spec.tz).hour,
                                                 instants=0, covered_instants=0, max_band_fraction=0.0,
                                                 max_expected_bands=0, band_rows_ready=False)
                    cell["instants"] += 1
                    cell["max_expected_bands"] = max(cell["max_expected_bands"], expected)
                    cell["band_rows_ready"] = cell["band_rows_ready"] or band_ready
                    cell["max_band_fraction"] = max(cell["max_band_fraction"], round(fraction, 6))
                    if reason == "covered":
                        cell["covered_instants"] += 1
        if progress:
            progress(f"census day {day_name}: cells {len(cells)} instants {counts['instants']}")
    for cell in cells.values():
        cell["covered"] = cell["covered_instants"] > 0
    donor_dates = defaultdict(set)
    for cell in cells.values():
        if cell["covered"]:
            donor_dates[(cell["market"], cell["lead"], cell["local_hour"])].add(cell["target"])
    for cell in cells.values():
        cell["donor_flagged"] = cell["covered"] and len(
            donor_dates[(cell["market"], cell["lead"], cell["local_hour"])]) >= DONOR_MIN_DATES
    return cells, counts, instant_reasons


def histogram(values):
    bins = Counter()
    for v in values:
        if v >= 1.0:
            bins["1.0"] += 1
            continue
        for lo, hi in zip(HIST_EDGES, HIST_EDGES[1:]):
            if lo <= v < hi:
                bins[f"[{lo:.1f},{hi:.1f})"] += 1
                break
    return dict(sorted(bins.items()))


def summarise(cells, counts, instant_reasons):
    by_lead = {}
    for lead in LEADS:
        rows = [c for c in cells.values() if c["lead"] == lead]
        def block(selected):
            return dict(event_hours=len(selected), targets=len({c["target"] for c in selected}),
                        markets=len({c["market"] for c in selected}),
                        dates=sorted({c["target"] for c in selected}),
                        market_ids=sorted({c["market"] for c in selected}),
                        per_market=dict(sorted(Counter(c["market"] for c in selected).items())),
                        per_target=dict(sorted(Counter(c["target"] for c in selected).items())))
        by_lead[str(lead)] = dict(
            all_cells=block(rows),
            covered_raw=block([c for c in rows if c["covered"]]),
            covered_donor_flagged=block([c for c in rows if c["donor_flagged"]]),
            band_fraction_histogram_per_cell_max=histogram([c["max_band_fraction"] for c in rows]),
            expected_bands_distribution=dict(sorted(Counter(str(c["max_expected_bands"]) for c in rows).items())),
            instant_reasons=dict(sorted((r, n) for (l, r), n in instant_reasons.items() if l == lead)))
    lead1 = by_lead["1"]["covered_donor_flagged"]
    failures = []
    if lead1["event_hours"] < CLOSE_MIN_EVENT_HOURS:
        failures.append(f"donor-flagged lead-1 event-hours {lead1['event_hours']} < {CLOSE_MIN_EVENT_HOURS}")
    if lead1["targets"] < CLOSE_MIN_TARGETS:
        failures.append(f"targets {lead1['targets']} < {CLOSE_MIN_TARGETS}")
    if lead1["markets"] < CLOSE_MIN_MARKETS:
        failures.append(f"markets {lead1['markets']} < {CLOSE_MIN_MARKETS}")
    close = dict(rule="UNTESTABLE if donor-flagged lead-1 event-hours < 200, targets < 10 or markets < 5 "
                      "(master ruling R28b (1), fixed before the census)",
                 outcome="UNTESTABLE" if failures else "CLEARS_FLOOR", failures=failures,
                 note="Upper bound under method rule 2, not a rule-16 projection; master rules on the receipt.")
    return dict(by_lead=by_lead, close_rule=close, counts=dict(sorted(counts.items())))


def git_state(repo):
    def run(*args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                              check=False).stdout.strip()
    return dict(head=run("rev-parse", "HEAD"), branch=run("rev-parse", "--abbrev-ref", "HEAD"),
                porcelain=run("status", "--porcelain", "--untracked-files=no"))


def write_new(path, data):
    with open(path, "xb") as handle:
        handle.write(data)
    return sha256_bytes(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--export-root", type=Path, required=True)
    parser.add_argument("--prior-archive", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="new directory; must not exist")
    args = parser.parse_args(argv)
    started = time.time()
    export_root, out = args.export_root.resolve(), args.out.resolve()
    if out.exists() or not out.parent.is_dir():
        parser.exit(2, "census refused: new output directory with an existing parent required\n")
    if out.is_relative_to(export_root) or out.is_relative_to(args.prior_archive.resolve()):
        parser.exit(2, "census refused: output inside an input root\n")
    def progress(msg):
        print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}", flush=True)
    import weather.market.market_registry as registry_module
    origin = Path(registry_module.__file__).resolve()
    if not origin.is_relative_to(Path(__file__).resolve().parents[3]):
        parser.exit(2, f"census refused: weather imported from outside this tree: {origin}\n")
    try:
        progress("integrity: start (refuse on any mismatch before any segment is parsed)")
        integrity = verify_inputs(export_root, args.prior_archive, progress)
        progress(f"integrity: MATCH export {integrity['export']['files_verified']} files, "
                 f"prior {integrity['prior_archive']['files_verified']} files")
        cells, counts, reasons = run_census(export_root, progress)
    except (Refused, ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f"census refused: {type(exc).__name__}: {exc}\n")
    summary = summarise(cells, counts, reasons)
    out.mkdir()
    cell_rows = sorted(cells.values(), key=lambda c: (c["lead"], c["market"], c["target"], c["utc_hour"]))
    cells_sha = write_new(out / "cells.jsonl", b"".join(encoded(c) + b"\n" for c in cell_rows))
    summary_doc = dict(schema=SCHEMA, scope=dict(capture_days=[FIRST_DAY.isoformat(), LAST_DAY.isoformat()],
                       targets=[FIRST_TARGET.isoformat(), LAST_TARGET.isoformat()],
                       excluded_market_days=[f"{m}:{d.isoformat()}" for m, d in sorted(EXCLUDED_MARKET_DAYS)],
                       leads=list(LEADS), donor_min_dates=DONOR_MIN_DATES), **summary)
    summary_sha = write_new(out / "summary.json", json.dumps(summary_doc, indent=1, sort_keys=True).encode() + b"\n")
    tool = Path(__file__).resolve()
    repo = tool.parents[3]
    receipt = dict(schema=SCHEMA + ":receipt", lane="L41", item="R28b", ruling_sha256=(
        "2499b5afec7a258378da9235689b594ae72a7c9f627d79c3b8c64ad489e2b44d"),
        tool=dict(path=str(tool.relative_to(repo)).replace("\\", "/"), sha256=sha256_file(tool)),
        git=git_state(repo), weather_origin=str(origin), python=sys.version.split()[0], platform=platform.platform(),
        argv=[str(a) for a in (argv if argv is not None else sys.argv[1:])],
        integrity=integrity, outputs={"cells.jsonl": cells_sha, "summary.json": summary_sha},
        cells=len(cell_rows), close_rule=summary["close_rule"],
        elapsed_seconds=round(time.time() - started, 1),
        finished_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        read_discipline="ids, flags, list lengths and timestamps only; no price, size, label, settlement or "
                        "fair value read into outputs; settlements/ never opened")
    receipt_sha = write_new(out / "receipt.json", json.dumps(receipt, indent=1, sort_keys=True).encode() + b"\n")
    progress(f"done: cells {len(cell_rows)}; close rule {summary['close_rule']['outcome']}; "
             f"receipt sha256 {receipt_sha}")
    print(json.dumps(dict(close_rule=summary["close_rule"], receipt_sha256=receipt_sha,
                          lead1_donor=summary["by_lead"]["1"]["covered_donor_flagged"]["event_hours"]),
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
