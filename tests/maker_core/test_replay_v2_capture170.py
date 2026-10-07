"""Maker replay v2 X1 fix round 1: a reproducible capture170 fixture and a format-aware ``s2 books``.

Fictional rows only (X1 Defender point 5 and M2).
"""
from datetime import date
import json

import pytest

from maker_core.evidence.journal import canonical_bytes
from tests.maker_core.test_replay_v2_writer import Day
from tools.research.maker_replay_v2 import s2
from tools.research.maker_replay_v2.capture170 import write
from tools.research.maker_replay_v2.fixture170 import Day as Day170
from tools.research.maker_replay_v2.run import write_forms
from maker_core.replay.v2.writer import BundleWriter
from weather.market import maker_evidence_store

DAY = date(2026, 9, 27)
SMALL = dict(union=144, trades=20, book_depth=2, minutes=3)


def _tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_two_capture170_generations_are_byte_identical(tmp_path):
    # Before the fix, uuid4 segment names flowed into subscription refs, manifests and ``sealed_segment``.
    original = maker_evidence_store.uuid4
    first = write(tmp_path / "a", DAY, **SMALL)
    second = write(tmp_path / "b", DAY, **SMALL)
    assert maker_evidence_store.uuid4 is original  # the production factory is restored afterwards
    a, b = _tree(tmp_path / "a"), _tree(tmp_path / "b")
    segments = {path.split("/")[2] for path in a if path.startswith("maker_evidence/")}
    assert segments and all(len(name) == len("00-") + 12 for name in segments)
    assert first == second
    assert list(a) == list(b)
    assert all(a[path] == b[path] for path in a)
    other = write(tmp_path / "c", DAY, seed=1, **SMALL)  # a different seed still names segments differently
    assert {p.split("/")[2] for p in _tree(tmp_path / "c") if p.startswith("maker_evidence/")} != segments
    assert other["recorded"]


def _write(folder, day, **kwargs):
    writer = BundleWriter(folder, spill_bytes=512, **kwargs)
    for value in day.rows:
        writer.add(value, canonical_bytes(value))
    return writer.finish(day.manifest(), day.groups)


def test_book_lines_reads_book_records_from_every_bundle_format(tmp_path):
    day = Day()
    _write(tmp_path / "v03", day)
    _write(tmp_path / "v02", day, compress=False)
    assert (tmp_path / "v03" / "book.jsonl.gz").is_file() and not (tmp_path / "v03" / "book.jsonl").exists()
    v03, v02 = list(s2.book_lines(tmp_path / "v03")), list(s2.book_lines(tmp_path / "v02"))
    assert v03 and v03 == v02 == (tmp_path / "v02" / "book.jsonl").read_bytes().splitlines(keepends=True)
    forms = write_forms(Day170(DAY, union=60, trades=50, start_minute=230, minutes=5), tmp_path / "f")
    v01 = list(s2.book_lines(forms["v01"]))
    assert v01 and all(json.loads(line)["kind"] == "book" for line in v01)
    assert v01 == list(s2.book_lines(forms["v02"]))


def test_book_lines_refuses_an_unknown_format(tmp_path):
    (tmp_path / "bundle.json").write_bytes(b'{"format": "maker_core.replay.bundle.v9"}')
    with pytest.raises(ValueError, match="unsupported bundle format"):
        list(s2.book_lines(tmp_path))


def test_books_measures_a_default_v03_export(tmp_path):
    # M2: the exporter writes book.jsonl.gz by default; the measurement must not look for book.jsonl.
    result = s2.books(DAY, tmp_path / "out", depths=[1, 3], minutes=2, union=144, trades=10)
    rows = result["rows"]
    assert [r["depth"] for r in rows] == [1, 3]
    assert all(r["format"] == "v0.3" and r["stored_bytes"] < r["bytes"] for r in rows)
    assert rows[0]["mean_levels_a_side"] < rows[1]["mean_levels_a_side"]
    assert result["fit"]["bytes_per_level_a_side"] > 0
