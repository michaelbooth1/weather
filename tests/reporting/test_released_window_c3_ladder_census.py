"""Synthetic tests for the R28b C3 ladder census. No real data is read; every layout is built under tmp_path."""
from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from tools.research.released_window import c3_ladder_census as census
from weather.market.market_registry import BUILTIN_SPECS

SPECS = {spec.id: spec for spec in BUILTIN_SPECS}
MONTHS = {9: "september", 10: "october"}
PRICE_SENTINEL = "0.4242"  # must never appear in any census output


def slug(market, month, day):
    return f"{SPECS[market].slug_prefix}-{MONTHS[month]}-{day}-2026"


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def band(cid, yes, no, **flags):
    row = dict(id=cid, conditionId=cid, clobTokenIds=json.dumps([yes, no]), outcomes=json.dumps(["Yes", "No"]),
               active=True, closed=False, enableOrderBook=True, rewardsMaxSpread=3, rewardsMinSize=50)
    row.update(flags)
    return row


def book(asset, cid, bids=1, asks=1):
    level = {"price": PRICE_SENTINEL, "size": "10"}
    return dict(asset_id=asset, market=cid, bids=[level] * bids, asks=[level] * asks, hash="h",
                last_trade_price=PRICE_SENTINEL, min_order_size="5", neg_risk=True, tick_size="0.01",
                timestamp="0")


class SegmentWriter:
    """Writes one sealed maker_evidence_v2 segment: books rows reference per-asset book files via parts."""

    def __init__(self, root, day, hour):
        self.folder = root / "data" / "maker_evidence" / day / f"{hour:02d}-0123456789ab"
        self.folder.mkdir(parents=True)
        self.files, self.seq = {}, 0
        self.books_rows, self.discovery_rows, self.book_files = [], [], {}

    def _next(self):
        self.seq += 1
        return self.seq

    def discovery(self, at, events):
        body = json.dumps(events).encode()
        digest = hashlib.sha256(body).hexdigest()
        self.discovery_rows.append(dict(kind="discovery", http_status=200, captured_at_utc=iso(at),
                                        sequence=self._next(), body_utf8=body.decode(), body_stored=True,
                                        representation="selection_projection", stored_sha256=digest,
                                        response_sha256=digest))

    def books(self, at, books):
        parts, chunks = [dict(literal_utf8="[")], [b"["]
        for i, item in enumerate(books):
            name = f"book-{item['asset_id']}.jsonl"
            rows = self.book_files.setdefault(name, [])
            body = json.dumps(item)
            rows.append(dict(sequence=self._next(), body_utf8=body))
            parts.append(dict(file=name, index=len(rows) - 1))
            chunks.append(body.encode())
            if i < len(books) - 1:
                parts.append(dict(literal_utf8=","))
                chunks.append(b",")
        parts.append(dict(literal_utf8="]"))
        chunks.append(b"]")
        raw = b"".join(chunks)
        self.books_rows.append(dict(kind="books", http_status=200, captured_at_utc=iso(at), sequence=self._next(),
                                    parts=parts, body_stored=True, response_sha256=hashlib.sha256(raw).hexdigest()))

    def _write(self, name, rows):
        lines, offset, last = [], 0, 0
        offsets = []
        for row in rows:
            row = dict(row, offset=offset)
            line = (json.dumps(row) + "\n").encode()
            lines.append(line)
            offsets.append(offset)
            last = offset
            offset += len(line)
        raw = b"".join(lines)
        with gzip.open(self.folder / (name + ".gz"), "wb") as handle:
            handle.write(raw)
        self.files[name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), records=len(rows),
                                last_offset=last, stream_capped=False, stream_response_bytes=0)
        return offsets

    def seal(self, sealed_at):
        offsets = {name: self._write(name, rows) for name, rows in self.book_files.items()}
        for row in self.books_rows:
            for part in row["parts"]:
                if "index" in part:
                    part["offset"] = offsets[part["file"]][part.pop("index")]
        self._write("books.jsonl", self.books_rows)
        self._write("discovery.jsonl", self.discovery_rows)
        manifest = dict(schema_version="maker_evidence_v2", sealed_at_utc=iso(sealed_at), files=self.files,
                        stream_capped=False, stream_response_bytes=0)
        with gzip.open(self.folder / "manifest.json.gz", "wb") as handle:
            handle.write(json.dumps(manifest).encode())


def snapshot_tokens(root, event_slug, at):
    folder = root / "data" / "snapshots" / event_slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "clob_tokens.jsonl").write_text(json.dumps(dict(captured_at_utc=iso(at), event_slug=event_slug)) + "\n",
                                              encoding="utf-8")


def ladder(prefix, n=3):
    return [(f"0x{prefix}{i}", f"{prefix}{i}1", f"{prefix}{i}2") for i in range(n)]


def full_books(bands, **overrides):
    out = []
    for cid, yes, no in bands:
        out.append(book(yes, cid, **overrides.get(yes, {})))
        out.append(book(no, cid))
    return out


# NYC (America/New_York, UTC-4 in late September). Capture 2026-09-25 16:10Z = 12:10 local -> target 09-26 lead 1.
def build_root(tmp_path, *, nyc_dates=(25, 26), drop_no=False, empty_yes_bid=False, band_rows=True,
               austin=False):
    root = tmp_path / "export"
    for day in nyc_dates:
        at = datetime(2026, 9, day, 16, 10, tzinfo=timezone.utc)
        writer = SegmentWriter(root, f"2026-09-{day:02d}", 16)
        target = slug("nyc", 9, day + 1)
        bands = ladder(f"n{day}")
        events = [dict(id="e", slug=target, markets=[band(*b) for b in bands])]
        books = full_books(bands, **({bands[0][1]: dict(bids=0)} if empty_yes_bid else {}))
        if drop_no:
            books = [b for b in books if b["asset_id"] != bands[-1][2]]
        if austin:
            a_bands = ladder("a")
            a_slug = slug("austin", 10, 3)
            events.append(dict(id="a", slug=a_slug, markets=[band(*b) for b in a_bands]))
            books += full_books(a_bands)
        writer.discovery(at - timedelta(seconds=5), events)
        writer.books(at, books)
        writer.seal(at.replace(minute=0) + timedelta(hours=1))
        if band_rows:
            snapshot_tokens(root, target, at - timedelta(hours=10))
    return root


def run(root):
    cells, counts, reasons = census.run_census(root)
    return {(c["market"], c["target"], c["lead"]): c for c in cells.values()}, counts, reasons


# ----------------------------------------------------------------------------- cell rule

def test_full_ladder_instant_is_covered_and_donor_flag_needs_two_dates(tmp_path):
    cells, counts, _ = run(build_root(tmp_path))
    first = cells[("nyc", "2026-09-26", 1)]
    second = cells[("nyc", "2026-09-27", 1)]
    assert first["covered"] and second["covered"]
    assert first["local_hour"] == second["local_hour"] == 12
    assert first["donor_flagged"] and second["donor_flagged"]
    assert first["max_band_fraction"] == 1.0 and first["max_expected_bands"] == 3


def test_single_covered_date_is_not_donor_flagged(tmp_path):
    cells, _, _ = run(build_root(tmp_path, nyc_dates=(25,)))
    cell = cells[("nyc", "2026-09-26", 1)]
    assert cell["covered"] and not cell["donor_flagged"]


def test_missing_no_book_breaks_coverage(tmp_path):
    cells, _, reasons = run(build_root(tmp_path, drop_no=True))
    cell = cells[("nyc", "2026-09-26", 1)]
    assert not cell["covered"]
    assert cell["max_band_fraction"] == pytest.approx(2 / 3, abs=1e-6)
    assert reasons[(1, "yes_or_no_book_absent")] == 2


def test_empty_yes_bid_list_breaks_coverage(tmp_path):
    cells, _, reasons = run(build_root(tmp_path, empty_yes_bid=True))
    assert not cells[("nyc", "2026-09-26", 1)]["covered"]
    assert reasons[(1, "yes_side_empty")] == 2


def test_band_rows_after_instant_break_coverage(tmp_path):
    cells, _, reasons = run(build_root(tmp_path, band_rows=False))
    cell = cells[("nyc", "2026-09-26", 1)]
    assert cell["max_band_fraction"] == 1.0 and not cell["covered"]
    assert reasons[(1, "band_rows_absent")] == 2


def test_closed_or_orderbook_disabled_bands_are_not_expected(tmp_path):
    bands = ladder("x", 3)
    event = dict(slug="s", markets=[band(*bands[0]), band(*bands[1], closed=True),
                                    band(*bands[2], enableOrderBook=False)])
    books = {b["asset_id"]: (b["market"], len(b["bids"]), len(b["asks"])) for b in full_books(bands[:1])}
    fraction, expected, reason = census.instant_fraction(event, books, True)
    assert (fraction, expected, reason) == (1.0, 1, "covered")


def test_austin_1003_is_excluded(tmp_path):
    # Capture 09-25 cannot reach target 10-03 at lead 1/2, so test the scope gate directly as well.
    assert not census.in_scope("austin", datetime(2026, 10, 3).date())
    assert census.in_scope("austin", datetime(2026, 10, 4).date())
    assert not census.in_scope("nyc", datetime(2026, 10, 9).date())
    with pytest.raises(census.Refused):
        census.in_scope("nyc", datetime(2026, 10, 15).date())


def test_embargoed_capture_day_folder_refuses(tmp_path):
    root = build_root(tmp_path, nyc_dates=(25,))
    (root / "data" / "maker_evidence" / "2026-10-15").mkdir()
    with pytest.raises(census.Refused, match="embargoed_capture_day"):
        census.run_census(root)


def test_tampered_sealed_file_refuses(tmp_path):
    root = build_root(tmp_path, nyc_dates=(25,))
    folder = next((root / "data" / "maker_evidence" / "2026-09-25").iterdir())
    path = folder / "discovery.jsonl.gz"
    raw = gzip.decompress(path.read_bytes()).replace(b"active", b"activf", 1)
    path.write_bytes(gzip.compress(raw))
    with pytest.raises(ValueError, match="sealed_file_hash_or_size_mismatch"):
        census.run_census(root)


# ----------------------------------------------------------------------------- integrity

def write_sums(root, extra=()):
    lines = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel in ("SHA256SUMS", *extra):
            continue
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {rel}\n")
    (root / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")
    return hashlib.sha256((root / "SHA256SUMS").read_bytes()).hexdigest(), len(lines)


def test_verify_tree_matches_then_refuses_on_tamper_and_unlisted(tmp_path):
    root = build_root(tmp_path, nyc_dates=(25,))
    sums_sha, count = write_sums(root)
    assert census.verify_tree(root, "SHA256SUMS", sums_sha, count)["result"] == "MATCH"
    with pytest.raises(census.Refused, match="sums_sha_mismatch"):
        census.verify_tree(root, "SHA256SUMS", "0" * 64, count)
    (root / "stray.txt").write_text("x", encoding="utf-8")
    with pytest.raises(census.Refused, match="unlisted_files"):
        census.verify_tree(root, "SHA256SUMS", sums_sha, count)
    (root / "stray.txt").unlink()
    target = next(p for p in root.rglob("clob_tokens.jsonl"))
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(census.Refused, match="file_sha_mismatch"):
        census.verify_tree(root, "SHA256SUMS", sums_sha, count)


def test_verify_inputs_pins_receipt_and_prior_named_files(tmp_path):
    export = build_root(tmp_path, nyc_dates=(25,))
    (export / "receipt.json").write_text("{}", encoding="utf-8")
    export_sha, export_count = write_sums(export, extra=("receipt.json",))
    prior = tmp_path / "prior"
    (prior / "run").mkdir(parents=True)
    (prior / "run" / "r.json").write_text("r", encoding="utf-8")
    prior_sha, prior_count = write_sums(prior)
    named = (("run/r.json", hashlib.sha256(b"r").hexdigest()),)
    receipt_sha = hashlib.sha256(b"{}").hexdigest()
    pins = dict(prior_sums=prior_sha, prior_count=prior_count, prior_named=named, export_receipt=receipt_sha,
                export_sums=export_sha, export_count=export_count)
    result = census.verify_inputs(export, prior, pins=pins)
    assert result["export"]["result"] == result["prior_archive"]["result"] == "MATCH"
    with pytest.raises(census.Refused, match="export_receipt_sha_mismatch"):
        census.verify_inputs(export, prior, pins=dict(pins, export_receipt="0" * 64))
    with pytest.raises(census.Refused, match="prior_named_file"):
        census.verify_inputs(export, prior, pins=dict(pins, prior_named=(("run/r.json", "0" * 64),)))


# ----------------------------------------------------------------------------- outputs

def test_summary_close_rule_and_no_price_in_outputs(tmp_path, monkeypatch):
    root = build_root(tmp_path, austin=True)
    (root / "receipt.json").write_text("{}", encoding="utf-8")
    sums_sha, count = write_sums(root, extra=("receipt.json",))
    prior = tmp_path / "prior"
    prior.mkdir()
    (prior / "a.txt").write_text("a", encoding="utf-8")
    prior_sha, prior_count = write_sums(prior)
    monkeypatch.setattr(census, "EXPORT_SUMS_SHA256", sums_sha)
    monkeypatch.setattr(census, "EXPORT_FILE_COUNT", count)
    monkeypatch.setattr(census, "EXPORT_RECEIPT_SHA256", hashlib.sha256(b"{}").hexdigest())
    monkeypatch.setattr(census, "PRIOR_SUMS_SHA256", prior_sha)
    monkeypatch.setattr(census, "PRIOR_FILE_COUNT", prior_count)
    monkeypatch.setattr(census, "PRIOR_LAUNCHER_RECEIPT", ("a.txt", hashlib.sha256(b"a").hexdigest()))
    monkeypatch.setattr(census, "PRIOR_POSTRUN_LOG", ("a.txt", hashlib.sha256(b"a").hexdigest()))
    out = tmp_path / "out"
    assert census.main(["--export-root", str(root), "--prior-archive", str(prior), "--out", str(out)]) == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    lead1 = summary["by_lead"]["1"]["covered_donor_flagged"]
    assert lead1["event_hours"] == 2 and lead1["markets"] == 1 and lead1["targets"] == 2
    assert summary["close_rule"]["outcome"] == "UNTESTABLE"
    assert len(summary["close_rule"]["failures"]) == 3
    assert "austin" not in json.dumps(summary["by_lead"])
    receipt = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["outputs"]["cells.jsonl"] == hashlib.sha256((out / "cells.jsonl").read_bytes()).hexdigest()
    for name in ("cells.jsonl", "summary.json", "receipt.json"):
        text = (out / name).read_text(encoding="utf-8")
        assert PRICE_SENTINEL not in text and '"price"' not in text and '"size"' not in text
    with pytest.raises(SystemExit):
        census.main(["--export-root", str(root), "--prior-archive", str(prior), "--out", str(out)])


def test_close_rule_clears_floor_when_all_thresholds_met():
    cells = {}
    for m, market in enumerate(("nyc", "atlanta", "austin", "chicago", "dallas")):
        for d in range(10):
            for h in range(4):
                key = (market, f"2026-09-{26 + d}", 1, f"h{h}")
                cells[key] = dict(market=market, target=f"2026-09-{26 + d}", lead=1, covered=True,
                                  donor_flagged=True, max_band_fraction=1.0, max_expected_bands=11)
    summary = census.summarise(cells, {}, {})
    assert summary["by_lead"]["1"]["covered_donor_flagged"]["event_hours"] == 200
    assert summary["close_rule"]["outcome"] == "CLEARS_FLOOR"
