"""Tests for gzip tiering of the canonical order_books.jsonl tape.

The refusals matter more than the happy path here: this module deletes canonical
evidence, so every guard gets a test that proves the source SURVIVES.
"""

from __future__ import annotations

import gzip
import json
import os
import time

import pytest

from weather.market.order_book_tape import (
    ACCEPTED_REPRESENTATIONS,
    iter_full_book_rows,
    resolve_full_book_representation,
)
from weather.operations import clob_raw_tape_tiering as tiering


RAW = tiering.RAW_TAPE
RAW_GZ = tiering.RAW_TAPE_GZIP


def _aged(path, seconds=None):
    """Backdate mtime past MIN_QUIET_SECONDS so the quiet check passes."""
    seconds = seconds if seconds is not None else tiering.MIN_QUIET_SECONDS + 600
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def _book_record(price="0.55"):
    return {
        "capture_id": "cap-1",
        "captured_at_utc": "2026-06-01T12:00:00+00:00",
        "token": {"token_id": "t-1", "outcome": "Yes", "market_id": "m-1"},
        "book": {"bids": [{"price": price, "size": "10"}], "asks": []},
    }


def _make_day(root, slug, *, lines=3, long_csv=False, lock=False):
    folder = root / slug
    folder.mkdir(parents=True)
    raw = folder / RAW
    raw.write_text(
        "".join(json.dumps(_book_record()) + "\n" for _ in range(lines)),
        encoding="utf-8",
    )
    if long_csv:
        (folder / tiering.ORDER_BOOK_LONG).write_text("header\n", encoding="utf-8")
    if lock:
        (folder / "order_books.jsonl.lock").write_text("", encoding="utf-8")
    _aged(raw)
    return folder, raw


SETTLED = "highest-temperature-in-nyc-on-june-1-2026"
CUTOFF = "2026-06-02"


def test_candidate_is_compressed_and_source_removed(tmp_path):
    folder, raw = _make_day(tmp_path, SETTLED)
    original = raw.read_bytes()

    payload = tiering.run(
        snapshots_root=tmp_path,
        settled_before=CUTOFF,
        min_free_bytes=0,
        apply=True,
        delete_source=True,
    )

    assert payload["status"] == "PASS"
    action = payload["apply"]["actions"][0]
    assert action["status"] == "compressed"
    assert action["source_deleted"] is True
    assert not raw.exists()

    gz = folder / RAW_GZ
    assert gz.exists()
    # The whole safety argument is that these are the same bytes.
    assert gzip.decompress(gz.read_bytes()) == original
    assert action["gzip_payload_sha256"] == action["source_sha256"]
    assert action["gzip_line_count"] == action["source_line_count"] == 3
    assert payload["apply"]["summary"]["reclaimed_bytes"] == (
        action["source_bytes"] - action["gzip_bytes"]
    )


def test_plan_never_mutates_anything(tmp_path):
    folder, raw = _make_day(tmp_path, SETTLED)
    before = raw.read_bytes()

    payload = tiering.run(snapshots_root=tmp_path, settled_before=CUTOFF, apply=False)

    assert payload["status"] == "WARN"  # a candidate exists
    assert payload["apply"] == {"enabled": False}
    assert raw.read_bytes() == before
    assert not (folder / RAW_GZ).exists()


def test_apply_without_delete_keeps_the_source(tmp_path):
    folder, raw = _make_day(tmp_path, SETTLED)

    payload = tiering.run(
        snapshots_root=tmp_path,
        settled_before=CUTOFF,
        min_free_bytes=0,
        apply=True,
        delete_source=False,
    )

    assert payload["apply"]["actions"][0]["source_deleted"] is False
    assert raw.exists()
    assert (folder / RAW_GZ).exists()


# --- the refusals -------------------------------------------------------------


def test_refuses_while_projection_tier_still_needs_the_raw(tmp_path):
    """closed_day_projection_tiering blocks on canonical_order_books_jsonl_missing."""
    folder, raw = _make_day(tmp_path, SETTLED, long_csv=True)

    payload = tiering.run(
        snapshots_root=tmp_path, settled_before=CUTOFF, min_free_bytes=0,
        apply=True, delete_source=True,
    )

    row = payload["rows"][0]
    assert row["status"] == "blocked_projection_tier_pending"
    assert row["recommended_action"] == "run_clob_order_book_tiering_first"
    assert payload["apply"]["actions"] == []
    assert raw.exists()


def test_refuses_when_a_writer_lock_is_present(tmp_path):
    folder, raw = _make_day(tmp_path, SETTLED, lock=True)

    payload = tiering.run(snapshots_root=tmp_path, settled_before=CUTOFF, apply=False)

    row = payload["rows"][0]
    assert row["status"] == "blocked_writer_lock_present"
    assert row["writer_locks"] == ["order_books.jsonl.lock"]
    assert raw.exists()


def test_refuses_a_recently_written_source(tmp_path):
    folder, raw = _make_day(tmp_path, SETTLED)
    os.utime(raw, None)  # touch: writer just appended

    payload = tiering.run(snapshots_root=tmp_path, settled_before=CUTOFF, apply=False)

    assert payload["rows"][0]["status"] == "blocked_recently_written"
    assert raw.exists()


def test_refuses_an_unsettled_day(tmp_path):
    folder, raw = _make_day(tmp_path, SETTLED)

    payload = tiering.run(snapshots_root=tmp_path, settled_before="2026-06-01", apply=False)

    assert payload["rows"][0]["status"] == "blocked_active_or_unsettled"
    assert raw.exists()


def test_quiet_recheck_happens_at_apply_time_not_only_at_plan_time(tmp_path):
    """A plan can be hours old; the writer may have come back since."""
    folder, raw = _make_day(tmp_path, SETTLED)
    payload = tiering.build_payload(tmp_path, settled_before=CUTOFF, min_free_bytes=0)
    assert payload["rows"][0]["status"] == "candidate"

    os.utime(raw, None)  # writer appended after the plan was taken
    applied = tiering.apply_tiering(payload, delete_source=True)

    assert applied["actions"][0]["status"] == "skipped_recently_written"
    assert raw.exists()
    assert not (folder / RAW_GZ).exists()


def test_refuses_on_insufficient_headroom(tmp_path):
    folder, raw = _make_day(tmp_path, SETTLED)

    payload = tiering.run(
        snapshots_root=tmp_path,
        settled_before=CUTOFF,
        min_free_bytes=1 << 62,  # unsatisfiable
        apply=True,
        delete_source=True,
    )

    assert payload["status"] == "BLOCKED"
    assert payload["apply"]["actions"][0]["status"] == "skipped_insufficient_headroom"
    assert raw.exists()


def test_split_day_with_both_present_is_never_auto_deleted(tmp_path):
    folder, raw = _make_day(tmp_path, SETTLED)
    (folder / RAW_GZ).write_bytes(gzip.compress(b"{}\n"))

    payload = tiering.run(
        snapshots_root=tmp_path, settled_before=CUTOFF, min_free_bytes=0,
        apply=True, delete_source=True,
    )

    assert payload["rows"][0]["status"] == "already_tiered_source_present"
    assert payload["apply"]["actions"] == []
    assert raw.exists()


def test_verification_failure_leaves_no_partial_gzip(tmp_path, monkeypatch):
    folder, raw = _make_day(tmp_path, SETTLED)
    monkeypatch.setattr(
        tiering, "gzip_payload_sha256_and_line_count", lambda path: ("deadbeef", 999)
    )

    payload = tiering.run(
        snapshots_root=tmp_path, settled_before=CUTOFF, min_free_bytes=0,
        apply=True, delete_source=True,
    )

    action = payload["apply"]["actions"][0]
    assert action["status"] == "failed"
    assert "gzip verification failed" in action["error"]
    assert raw.exists()                       # source survived
    assert not (folder / RAW_GZ).exists()     # no half-written artifact
    assert not (folder / (RAW_GZ + ".tmp")).exists()


def test_path_escaping_snapshots_root_is_rejected(tmp_path):
    folder, raw = _make_day(tmp_path, SETTLED)
    payload = tiering.build_payload(tmp_path, settled_before=CUTOFF, min_free_bytes=0)
    payload["rows"][0]["source_path"] = str(tmp_path.parent / "elsewhere.jsonl")

    with pytest.raises(ValueError, match="escapes snapshots root"):
        tiering.apply_tiering(payload, delete_source=True)


# --- the read boundary --------------------------------------------------------


def test_order_book_tape_reads_the_gzip_as_canonical(tmp_path):
    folder, raw = _make_day(tmp_path, SETTLED, lines=2)
    expected, _ = iter_full_book_rows(folder)
    expected_rows = list(expected)

    tiering.run(
        snapshots_root=tmp_path, settled_before=CUTOFF, min_free_bytes=0,
        apply=True, delete_source=True,
    )

    provenance = resolve_full_book_representation(folder)
    assert provenance.representation == "raw_jsonl_gzip"
    assert provenance.canonical is True          # NOT a projection fallback
    assert provenance.fallback_reason is not None

    rows, _ = iter_full_book_rows(folder)
    assert list(rows) == expected_rows           # identical rows after tiering


def test_plain_raw_still_outranks_the_gzip(tmp_path):
    folder, raw = _make_day(tmp_path, SETTLED)
    (folder / RAW_GZ).write_bytes(gzip.compress(b"{}\n"))

    provenance = resolve_full_book_representation(folder)

    assert provenance.representation == "raw_jsonl"
    assert provenance.fallback_reason is None


def test_gzip_outranks_every_csv_projection(tmp_path):
    folder, raw = _make_day(tmp_path, SETTLED)
    (folder / tiering.ORDER_BOOK_LONG_GZIP).write_bytes(gzip.compress(b"x\n"))
    raw.rename(folder / RAW_GZ)  # stand in for a tiered day
    (folder / RAW_GZ).write_bytes(gzip.compress(b"{}\n"))

    provenance = resolve_full_book_representation(folder)

    assert provenance.representation == "raw_jsonl_gzip"
    assert ACCEPTED_REPRESENTATIONS.index("raw_jsonl_gzip") < ACCEPTED_REPRESENTATIONS.index(
        "gzip_csv"
    )
