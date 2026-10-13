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
    trades = result["coverage_by_channel"]["trades"]
    assert trades["wanted_basis"] == "inferred_from_session_rows"
    assert trades["token_dark_seconds_by_cause"] == {"venue_close": 20.0}
    assert trades["all_sockets_down_seconds"] == 20.0
    assert "dark_seconds_by_cause" not in result  # The per-subscription-key figure is gone.
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


class Writer:
    """Journal rows through the production store and stream writers at chosen fake times, in time order."""

    def __init__(self, root):
        self.now = [START]
        self.store = EvidenceStore(root, clock=lambda: self.now[0])
        self.trades = PublicStream(self.store, trades_only=True)

    def at(self, seconds):
        self.now[0] = START + timedelta(seconds=seconds)
        return self.now[0]

    def wanted(self, seconds, *chunks):
        self.at(seconds)
        self.trades._journal_tokens([tuple(chunk) for chunk in chunks])

    def connect(self, tokens, seconds):
        self.trades._lifecycle("connected", tuple(tokens), "trades", self.at(seconds))

    def disconnect(self, tokens, seconds, *, error=None):
        self.trades._lifecycle("disconnected", tuple(tokens), "trades", self.at(seconds))
        if error:
            self.store.event("stream_gap", {"channel": "trades", "error_type": error[0], "error": error[1],
                                            "subscription": self.store.subscription(tuple(tokens), "trades"),
                                            "backfill_claimed": False}, captured_at=self.at(seconds))

    def report(self):
        self.store.seal()
        return report.classify_stream_drops(self.store.root, local_date="2026-10-02")["coverage_by_channel"]["trades"]


@pytest.fixture
def writer(tmp_path, monkeypatch):
    monkeypatch.setattr(EvidenceStore, "free_bytes", lambda self: 100 * 1024**3)
    return Writer(tmp_path)


def test_token_coverage_is_the_union_across_overlapping_subscriptions(writer):
    writer.wanted(0, ("1", "2"))
    writer.connect(("1", "2"), 0.5)
    writer.wanted(100, ("1", "3"))
    writer.connect(("1", "3"), 100.4)  # Make-before-break: the new key connects before the old one closes.
    writer.disconnect(("1", "2"), 101)
    writer.wanted(200)
    writer.disconnect(("1", "3"), 200.5)
    trades = writer.report()
    assert trades["wanted_basis"] == "stream_tokens_rows" and trades["tokens_wanted"] == 3
    # Only each token's first connect latency is dark; the swap leaves token 1 no gap.
    assert trades["token_dark_seconds_by_cause"] == {"awaiting_connect": pytest.approx(1.4)}
    assert {item["token"]: item["dark_seconds"] for item in trades["darkest_tokens"]} == {
        "1": 0.5, "2": 0.5, "3": 0.4}
    assert trades["all_sockets_down_seconds"] == 0.5
    assert trades["active_seconds"] == 200.0


def test_all_sockets_down_needs_every_socket_on_the_channel_down(writer):
    close = ("VenueCloseError", "venue closed the websocket: code=1011 reason='overloaded'")
    writer.wanted(0, ("a",), ("b",))
    writer.connect(("a",), 0)
    writer.connect(("b",), 0)
    writer.disconnect(("a",), 300, error=close)
    writer.disconnect(("b",), 320, error=("TimeoutError", "public stream inbound silence"))
    writer.connect(("b",), 325)
    writer.connect(("a",), 330)
    writer.wanted(1000)
    writer.disconnect(("a",), 1000)
    writer.disconnect(("b",), 1000)
    trades = writer.report()
    assert trades["all_sockets_down_seconds"] == 5.0
    assert trades["all_sockets_down_gap_seconds"]["n"] == 1
    assert trades["token_dark_seconds_by_cause"] == {"silence_timeout": 5.0, "venue_close": 30.0}
    assert trades["token_dark_seconds_total"] == 35.0


@pytest.mark.parametrize("journaled_wanted", [True, False])
def test_swap_rekeying_does_not_inflate_darkness(writer, journaled_wanted):
    """The 2026-09-29 artifact: each swap rekeyed the socket, so the old key read "dark" until it came back."""
    sets = [("1", "2"), ("1", "3")]
    for swap in range(10):
        start, tokens = swap * 60, sets[swap % 2]
        if swap:
            writer.disconnect(sets[(swap - 1) % 2], start)
        if journaled_wanted:
            writer.wanted(start, tokens)
        # The old break-before-make swap: the next key connects 0.4 s after the last one closed.
        writer.connect(tokens, start + (0.4 if swap else 0.0))
    if journaled_wanted:
        writer.wanted(600)
    writer.disconnect(sets[1], 600)
    trades = writer.report()
    assert trades["wanted_basis"] == ("stream_tokens_rows" if journaled_wanted else "inferred_from_session_rows")
    # Token 1 is dark only for the nine 0.4 s gaps; tokens 2 and 3 are not dark while out of the set.
    darkest = {item["token"]: item["dark_seconds"] for item in trades["darkest_tokens"]}
    assert darkest["1"] == pytest.approx(3.6)
    assert trades["token_dark_seconds_by_cause"]["orderly_stop"] == pytest.approx(3.6)
    assert trades["all_sockets_down_seconds"] == pytest.approx(3.6)
    if journaled_wanted:  # A re-added token waits for its connect, and is dark only for that.
        assert darkest["2"] == pytest.approx(1.6) and darkest["3"] == pytest.approx(2.0)
    else:
        assert set(darkest) == {"1"}
