"""Offline parser and range-locator checks for the L12 NBM NBS/NBH station-block fetcher.

Guards: tools/research/nbm_nbs_nbh_fetch.py block format contract (fixed-width NBS/NBH station
blocks, columns resolved forward from the issue time, headers only at line starts, located block
is the whole station block and never a one-byte stub) and its 2026-09-29 date refusal.
"""
from datetime import date, datetime, timezone

import pytest

from tools.research import nbm_nbs_nbh_fetch as fetch


def _row(label, values):
    return f" {label} " + "".join("   " if v is None else f"{v:>3}" for v in values)


def _nbs_block(station, txn_at_00=77):
    utc = [18, 21, 0, 3, 6, 9, 12, 15]
    lines = [
        f" {station}  NBM V4.3 NBS GUIDANCE   11/15/2025  1200 UTC",
        " DT /NOV  15/NOV  16",
        _row("UTC", utc),
        _row("FHR", [6, 9, 12, 15, 18, 21, 24, 27]),
        _row("TXN", [None, None, txn_at_00, None, None, None, 64, None]),
        _row("TMP", [76, 76, 74, 72, 69, 67, 65, 73]),
        _row("CIG", [-88, -88, 42, -88, -88, -88, -88, -88]),
        " " * 60,
    ]
    return "\n".join(lines) + "\n"


def _nbh_block(station):
    utc = [13, 14, 23, 0, 1]
    lines = [
        f" {station} NBM V4.0 NBH GUIDANCE    8/01/2021  1200 UTC",
        _row("UTC", utc),
        _row("TMP", [70, 73, 75, 74, 73]),
        _row("P06", [None, None, 0, None, None]),
        " " * 60,
    ]
    return "\n".join(lines) + "\n"


def test_nbs_block_parses_txn_in_its_column_and_rolls_valid_time_past_midnight():
    parsed = fetch.parse_block(_nbs_block("KATL").encode())
    assert parsed["header"]["station"] == "KATL"
    assert parsed["header"]["product"] == "NBS"
    assert parsed["header"]["version"] == "V4.3"
    assert parsed["header"]["issued_utc"] == datetime(2025, 11, 15, 12, tzinfo=timezone.utc)
    assert parsed["fhr"] == [6, 9, 12, 15, 18, 21, 24, 27]
    assert parsed["rows"]["TXN"] == [None, None, 77, None, None, None, 64, None]
    assert parsed["rows"]["CIG"][:3] == [-88, -88, 42]
    valid = parsed["valid_utc"]
    assert valid[0] == datetime(2025, 11, 15, 18, tzinfo=timezone.utc)
    assert valid[2] == datetime(2025, 11, 16, 0, tzinfo=timezone.utc)
    assert valid[-1] == datetime(2025, 11, 16, 15, tzinfo=timezone.utc)
    # The forecast-hour row and the resolved valid times agree column by column.
    issued = parsed["header"]["issued_utc"]
    assert [int((v - issued).total_seconds() // 3600) for v in valid] == parsed["fhr"]


def test_nbh_block_first_column_is_the_hour_after_issue_and_missing_cells_are_none():
    parsed = fetch.parse_block(_nbh_block("KLAX").encode())
    assert parsed["header"]["issued_utc"] == datetime(2021, 8, 1, 12, tzinfo=timezone.utc)
    assert parsed["fhr"] is None
    assert parsed["rows"]["TMP"] == [70, 73, 75, 74, 73]
    assert parsed["rows"]["P06"] == [None, None, 0, None, None]
    assert [v.hour for v in parsed["valid_utc"]] == [13, 14, 23, 0, 1]
    assert parsed["valid_utc"][3].day == 2


def test_parse_rejects_a_block_without_a_header():
    with pytest.raises(ValueError):
        fetch.parse_block(b" \n")


def test_header_matches_only_line_starts():
    data = b"xx KATL  NBM V4.3 NBS GUIDANCE  11/15/2025  1200 UTC\n KAUS  NBM V4.3 NBS GUIDANCE\n"
    assert [h[0] for h in fetch.header_matches(data)] == ["KAUS"]


BLOCKS = ["086092", "CYYZ", "KATL", "KATP", "KAUS", "KBKF", "KDAL"]
BULLETIN = ("1\n" + " " * 60 + "\n" + "".join(_nbs_block(s) for s in BLOCKS)).encode()
OBJ = {"key": "blend.20251115/12/text/blend_nbstx.t12z", "size": len(BULLETIN), "etag": "abc"}


class _Resp:
    def __init__(self, status, content):
        self.status_code = status
        self.content = content


class _Session:
    """Serves byte ranges of BULLETIN; enforces If-Match like S3."""

    def __init__(self):
        self.calls = 0

    def get(self, url, timeout=None, headers=None, params=None):
        self.calls += 1
        headers = headers or {}
        if headers.get("If-Match") != '"abc"':
            return _Resp(412, b"")
        lo, hi = headers["Range"].split("=")[1].split("-")
        return _Resp(206, BULLETIN[int(lo): int(hi) + 1])


def _fetcher():
    return fetch.Fetcher(_Session(), pause=0)


def _true_offset(station):
    return BULLETIN.index(f" {station}  NBM".encode())


@pytest.mark.parametrize("station", ["CYYZ", "KATL", "KBKF", "KDAL"])
def test_locate_by_bisect_returns_the_whole_block(station):
    off, block, how = _fetcher().locate(OBJ, station, None, 3600)
    assert how == "bisect"
    assert off == _true_offset(station)
    assert block.decode() == _nbs_block(station)


def test_locate_exact_guess_costs_one_read():
    f = _fetcher()
    off, block, how = f.locate(OBJ, "KAUS", _true_offset("KAUS"), 3600)
    assert (off, how) == (_true_offset("KAUS"), "guess")
    assert block.decode() == _nbs_block("KAUS")
    assert f.requests == 1


def test_locate_shifted_guess_falls_back_to_the_window():
    off, block, how = _fetcher().locate(OBJ, "KAUS", _true_offset("KAUS") + 2000, 300)
    assert (off, how) == (_true_offset("KAUS"), "window")
    assert block.decode() == _nbs_block("KAUS")


def test_short_read_extends_to_the_next_header_not_a_one_byte_stub():
    # Regression: with a block-length estimate shorter than the block, the extension path
    # once re-matched the station's own header and returned b" ".
    f = _fetcher()
    off = _true_offset("KATL")
    got = f._block_from(OBJ, BULLETIN[off: off + 100], off, "KATL")
    assert got is not None
    assert got[0] == off
    assert got[1].decode() == _nbs_block("KATL")


def test_absent_station_is_reported_not_guessed():
    off, block, how = _fetcher().locate(OBJ, "KAAA", None, 3600)
    assert (off, block, how) == (None, None, "station_absent")


def test_etag_change_mid_read_fails_loud():
    obj = dict(OBJ, etag="other")
    with pytest.raises(RuntimeError, match="ETag"):
        _fetcher().read(obj, 0, 100)


def test_fetch_object_records_offsets_and_hashes_that_reproduce_the_blocks():
    import hashlib

    blob, rows = fetch.fetch_object(_fetcher(), OBJ, ["KATL", "KBKF"], {}, {}, "nbs")
    for st in ("KATL", "KBKF"):
        r = rows[st]
        piece = blob[r["file_offset"]: r["file_offset"] + r["length"]]
        assert piece == BULLETIN[r["bulletin_offset"]: r["bulletin_offset"] + r["length"]]
        assert hashlib.sha256(piece).hexdigest() == r["sha256"]
        assert fetch.parse_block(piece)["header"]["station"] == st


def test_plan_dates_refuses_after_the_evidence_cutoff():
    days = list(fetch.plan_dates([2025], [12]))
    assert days[0] == date(2025, 12, 1) and days[-1] == date(2025, 12, 31)
    with pytest.raises(SystemExit):
        list(fetch.plan_dates([2026], [9, 10]))
