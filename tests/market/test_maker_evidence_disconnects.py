"""88a stream drops are classified from journals written by the production store and stream."""
from datetime import datetime, timedelta, timezone

import pytest

from weather.market import maker_evidence_disconnects as report
from weather.market.maker_evidence_archive import compress_closed_segments
from weather.market.maker_evidence_store import EvidenceStore
from weather.market.maker_evidence_stream import PublicStream

START = datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)  # 10:00 America/Toronto


@pytest.fixture
def journals(tmp_path, monkeypatch):
    monkeypatch.setattr(EvidenceStore, "free_bytes", lambda self: 100 * 1024**3)
    now = [START]
    store = EvidenceStore(tmp_path, clock=lambda: now[0])
    trades, updates = PublicStream(store, trades_only=True), PublicStream(store)

    def at(seconds):
        now[0] = START + timedelta(seconds=seconds)
        return now[0]

    def lifecycle(stream, state, seconds, tokens):
        stream._lifecycle(state, tokens, "trades" if stream.trades_only else "updates", at(seconds))

    def gap(channel, tokens, error_type, error, seconds):
        # The row shape PublicStream._run writes.
        store.event("stream_gap", {"channel": channel, "error_type": error_type, "error": error,
                                   "subscription": store.subscription(tokens, channel),
                                   "backfill_claimed": False}, captured_at=at(seconds))

    lifecycle(trades, "connected", 0, ("1",))
    lifecycle(trades, "disconnected", 600, ("1",))
    gap("trades", ("1",), "VenueCloseError", "venue closed the websocket: code=1011 reason='overloaded'", 600)
    gap("trades", ("1",), "WebSocketBadStatusException", "Handshake status 429 Too Many Requests", 605)
    lifecycle(trades, "connected", 620, ("1",))
    lifecycle(updates, "connected", 3600, ("2",))
    lifecycle(updates, "disconnected", 3900, ("2",))  # Window end: no gap row.
    store.seal()
    compress_closed_segments(store)  # The first hour is read back from gzip.
    lifecycle(trades, "disconnected", 48600, ("1",))  # 03:30Z next UTC day = 23:30 local.
    gap("trades", ("1",), "TimeoutError", "public stream inbound silence", 48600)
    store.seal()
    return tmp_path


def test_drops_are_grouped_by_cause_channel_and_local_hour(journals):
    result = report.classify_stream_drops(journals, local_date="2026-10-02")
    assert any(item["path"].endswith(".jsonl.gz") for item in result["inputs"])
    assert result["socket_drops_total"] == 2
    assert result["socket_drops_by_channel_cause"] == {"trades:venue_close": 1, "trades:silence_timeout": 1}
    assert result["connect_failures_by_cause"] == {"handshake_rejected": 1}
    assert result["orderly_stops_by_channel"] == {"updates": 1}
    assert result["venue_close_codes"] == {"1011": 1}
    assert result["hourly_socket_drops"]["10"] == {"trades:venue_close": 1}
    assert result["hourly_socket_drops"]["23"] == {"trades:silence_timeout": 1}
    assert result["daytime_vs_overnight"]["daytime"]["socket_drops"] == 1
    assert result["daytime_vs_overnight"]["overnight"]["socket_drops"] == 1
    # Dark time runs from the drop, across the failed reconnect, to the next connect.
    assert result["dark_seconds_by_cause"]["venue_close"]["sum"] == 20.0
    assert result["session_lifetime_seconds_by_cause"]["venue_close"]["sum"] == 600.0
    assert result["session_lifetime_seconds_by_cause"]["silence_timeout"]["sum"] == 47980.0


def test_other_dates_are_excluded(journals):
    result = report.classify_stream_drops(journals, local_date="2026-10-03")
    assert result["socket_drops_total"] == 0 and result["connect_failures_by_cause"] == {}


@pytest.mark.parametrize("error_type, error, cause", [
    ("ConnectionError", "public socket closed", "empty_frame"),
    ("WebSocketConnectionClosedException", "Connection to remote host was lost.", "connection_lost"),
    ("ConnectionResetError", "[WinError 10054] An existing connection was forcibly closed", "connection_reset"),
    ("WebSocketProtocolException", "public message exceeds byte bound", "message_bound"),
    ("ValueError", "public trade channel received a non-object event", "bad_payload"),
    ("OSError", "[Errno 28] No space left on device", "journal_writer_error"),
    ("TimeoutError", "timed out", "socket_timeout"),
    ("gaierror", "[Errno 11001] getaddrinfo failed", "connect_failed"),
])
def test_gap_text_classification(error_type, error, cause):
    assert report.classify_gap(error_type, error) == cause


def test_cli_writes_json(journals, tmp_path):
    output = tmp_path / "report.json"
    assert report.main(["--root", str(journals), "--date", "2026-10-02", "--output", str(output)]) == 0
    assert '"socket_drops_total": 2' in output.read_text(encoding="utf-8")
