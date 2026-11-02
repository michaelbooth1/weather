"""tools.research.pm_price_history.fidcheck_v1: guards and distance maths (no network, synthetic data)."""

from __future__ import annotations

import gzip
import json

import pytest

from tools.research.pm_price_history import fidcheck_v1 as fc, guards


def test_partition_guard():
    assert fc.require_partition("2026-09-27") == "2026-09-27"
    for day in ("2026-09-28", "2026-09-30", "2026-10-05"):
        with pytest.raises(guards.GuardRefusal):
            fc.require_partition(day)


def test_book_view_mid_display_and_ms_timestamp():
    v = fc.book_view({"timestamp": "1758800000123", "bids": [{"price": "0.40"}, {"price": "0.42"}],
                      "asks": [{"price": "0.46"}, {"price": "0.50"}], "last_trade_price": "0.45"})
    assert v["ts"] == 1758800000 and v["mid"] == pytest.approx(0.44) and v["display"] == pytest.approx(0.44)
    v = fc.book_view({"timestamp": "1758800000", "bids": [{"price": "0.10"}], "asks": [{"price": "0.40"}],
                      "last_trade_price": "0.30"})
    assert v["display"] == pytest.approx(0.30)  # wide spread -> last trade
    assert fc.book_view({"bids": []}) is None


def test_nearest_respects_gap():
    stamps, prices = [0, 60, 120], [0.1, 0.2, 0.3]
    assert fc.nearest(stamps, prices, 90, "before") == 0.2
    assert fc.nearest(stamps, prices, 90, "after") == 0.3
    assert fc.nearest(stamps, prices, 500, "before") is None


def _write_gz(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(text.encode()))


def test_compare_end_to_end(tmp_path):
    run = tmp_path / "run"
    _write_gz(run / "raw/h.json.gz", json.dumps({"history": [{"t": 1000, "p": 0.44}, {"t": 1060, "p": 0.45}]}))
    (run / "tokens.jsonl").write_text(json.dumps({"yes_token": "111", "event_date": "2026-09-26",
                                                  "path": "raw/h.json.gz"}) + "\n")
    book = {"timestamp": "1030", "bids": [{"price": "0.42"}], "asks": [{"price": "0.46"}], "last_trade_price": "0.50"}
    ev = tmp_path / "ev"
    _write_gz(ev / "2026-09-25/12-x/book-111.jsonl.gz", json.dumps({"body_utf8": json.dumps(book)}) + "\n")
    _write_gz(ev / "2026-09-25/12-x/book-999.jsonl.gz", "not json, never parsed\n")
    out = fc.compare(run, ev, ["2026-09-25"])
    assert out["tokens_matched"] == 1 and out["book_snapshots"] == 1
    assert out["history_minus_reference"]["mid_before"]["median_abs"] == 0.0
    assert out["history_minus_reference"]["ltp_before"]["median_abs"] == pytest.approx(0.06)


def test_tokens_from_guarded_dates_refused(tmp_path):
    (tmp_path / "tokens.jsonl").write_text(json.dumps({"yes_token": "1", "event_date": "2026-09-30", "path": "x"}) + "\n")
    with pytest.raises(guards.GuardRefusal):
        fc.load_tokens(tmp_path)
