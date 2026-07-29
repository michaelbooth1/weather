import csv
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from weather.io import TieredTextConflictError
from weather.io import write_csv_rows
from weather.market.market_microstructure_capture import order_book_level_rows
from weather.market.market_microstructure_constants import BOOK_LEVEL_COLUMNS
from weather.market.order_book_tape import (
    GZIP_RAW_BOOK_FILENAME,
    iter_full_book_rows,
    rebuild_long_csv,
)


def _raw_record():
    captured_at = datetime(2026, 7, 1, 15, 0, tzinfo=timezone.utc)
    token = {
        "captured_at_local": "2026-07-01T11:00:00-04:00",
        "event_slug": "highest-temperature-in-nyc-on-july-1-2026",
        "market_id": "nyc",
        "polymarket_market_id": "market-1",
        "condition_id": "condition-1",
        "range_label": "90-91 F",
        "outcome": "Yes",
        "clob_token_id": "token-1",
    }
    book = {
        "asset_id": "token-1",
        "market": "condition-1",
        "hash": "book-hash",
        "bids": [
            {"price": "0.40", "size": "10"},
            {"price": "0.39", "size": "20"},
        ],
        "asks": [{"price": "0.45", "size": "12"}],
    }
    return {
        "capture_id": "capture-1",
        "captured_at_utc": captured_at.isoformat(),
        "event_slug": token["event_slug"],
        "market_id": token["market_id"],
        "clob_token_id": token["clob_token_id"],
        "token": token,
        "book": book,
    }, order_book_level_rows(book, token, captured_at, "capture-1")


def _write_raw(folder: Path):
    record, rows = _raw_record()
    folder.mkdir(parents=True)
    (folder / "order_books.jsonl").write_text(
        json.dumps(record, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return rows


def test_canonical_jsonl_rebuild_matches_the_writer_projection(tmp_path):
    folder = tmp_path / "event"
    expected = _write_raw(folder)
    output = tmp_path / "output" / "order_books_long.csv"

    proof = rebuild_long_csv(folder / "order_books.jsonl", output)
    with output.open("r", encoding="utf-8", newline="") as handle:
        rebuilt = list(csv.DictReader(handle))
    expected_path = tmp_path / "expected.csv"
    write_csv_rows(expected_path, BOOK_LEVEL_COLUMNS, expected)
    with expected_path.open("r", encoding="utf-8", newline="") as handle:
        expected_rows = list(csv.DictReader(handle))

    assert proof["row_count"] == len(expected)
    assert rebuilt == expected_rows
    assert output.read_bytes() == expected_path.read_bytes()


def test_full_book_reader_streams_jsonl_then_falls_back_to_gzip(tmp_path):
    folder = tmp_path / "event"
    _write_raw(folder)
    rebuilt = tmp_path / "rebuilt.csv"
    rebuild_long_csv(folder / "order_books.jsonl", rebuilt)

    raw_rows, raw_provenance = iter_full_book_rows(folder)
    raw_rows = list(raw_rows)

    with rebuilt.open("rb") as source, (
        folder / "order_books_long.csv.gz"
    ).open("wb") as raw_target:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_target,
            mtime=0,
        ) as target:
            target.write(source.read())
    (folder / "order_books.jsonl").unlink()
    gzip_rows, gzip_provenance = iter_full_book_rows(folder)
    gzip_rows = list(gzip_rows)

    assert raw_provenance.representation == "raw_jsonl"
    assert raw_provenance.canonical is True
    assert gzip_provenance.representation == "gzip_csv"
    assert gzip_provenance.fallback_reason == (
        "preferred representations unavailable: raw_jsonl,raw_jsonl_gzip"
    )
    assert len(raw_rows) == len(gzip_rows)
    assert [str(row["price"]) for row in raw_rows] == [row["price"] for row in gzip_rows]


def test_full_book_reader_transparently_reads_canonical_jsonl_gzip(tmp_path):
    folder = tmp_path / "event"
    expected = _write_raw(folder)
    raw = folder / "order_books.jsonl"
    compressed = folder / GZIP_RAW_BOOK_FILENAME
    with raw.open("rb") as source, compressed.open("wb") as raw_target:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_target,
            mtime=0,
        ) as target:
            target.write(source.read())
    raw.unlink()

    rows, provenance = iter_full_book_rows(folder)

    assert list(rows) == expected
    assert provenance.representation == "raw_jsonl_gzip"
    assert provenance.canonical is True
    assert provenance.path.endswith(GZIP_RAW_BOOK_FILENAME)


def test_divergent_long_pair_fails_before_canonical_rows_are_yielded(tmp_path):
    folder = tmp_path / "event"
    _write_raw(folder)
    plain = folder / "order_books_long.csv"
    plain.write_text("plain-half\n", encoding="utf-8")
    with (folder / "order_books_long.csv.gz").open("wb") as raw_target:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_target,
            mtime=0,
        ) as target:
            target.write(b"gzip-half\n")

    with pytest.raises(TieredTextConflictError):
        iter_full_book_rows(folder)


def test_identical_long_pair_does_not_block_canonical_reader(tmp_path):
    folder = tmp_path / "event"
    expected = _write_raw(folder)
    content = b"header\nidentical\n"
    (folder / "order_books_long.csv").write_bytes(content)
    with (folder / "order_books_long.csv.gz").open("wb") as raw_target:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_target,
            mtime=0,
        ) as target:
            target.write(content)

    rows, provenance = iter_full_book_rows(folder)

    assert list(rows) == expected
    assert provenance.representation == "raw_jsonl"


def test_failed_rebuild_leaves_no_partial_final_projection(tmp_path):
    raw = tmp_path / "order_books.jsonl"
    raw.write_text('{"capture_id":"incomplete"}\n', encoding="utf-8")
    output = tmp_path / "rebuilt" / "order_books_long.csv"

    try:
        rebuild_long_csv(raw, output)
    except ValueError:
        pass
    else:
        raise AssertionError("malformed canonical input should fail the rebuild")

    assert not output.exists()
    assert not output.with_name(f".{output.name}.tmp").exists()
