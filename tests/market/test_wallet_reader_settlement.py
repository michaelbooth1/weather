import json
import socket
import tracemalloc
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.market.test_wallet_reader import FIELDS, FUNDER, FakeOpener, wire
from weather.market import wallet_reader as core
from weather.market import wallet_reader_client as client
from weather.market import wallet_reader_security as security
from weather.market import wallet_reader_server as server
from weather.market import wallet_reader_settlement as settle

A, B, C, D = ("0x" + ch * 64 for ch in "abcd")
PREFIX = "highest-temperature-in-toronto-on"
SLUG_A, SLUG_B = PREFIX + "-september-20-2026", PREFIX + "-september-21-2026"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refused(*args, **kwargs):
        raise AssertionError("network forbidden in wallet-reader tests")
    monkeypatch.setattr(socket.socket, "connect", refused)
    monkeypatch.setattr(socket, "create_connection", refused)


@pytest.fixture
def guard():
    return security.SecretGuard(FIELDS[k] for k in ("API_KEY", "API_SECRET", "API_PASSPHRASE", "READER_TOKEN"))


def market(condition, prices, *, closed=True, slug=SLUG_A, title="16°C", source="https://www.weather.gov/wrh/timeseries?site=CYYZ"):
    return dict(conditionId=condition, closed=closed, active=not closed, question="q " + condition[:5],
                clobTokenIds=json.dumps([str("abcd".index(condition[2]) + 1) + "1", str("abcd".index(condition[2]) + 1) + "2"]), outcomes=json.dumps(["Yes", "No"]),
                outcomePrices=json.dumps(prices), groupItemTitle=title, resolutionSource=source,
                umaResolutionStatus="resolved" if closed else None, events=[{"slug": slug}])


POSITIONS = [
    dict(proxyWallet=FUNDER, asset="11", conditionId=A, size=10, avgPrice=.4, redeemable=True, eventSlug=SLUG_A,
         outcome="Yes", title="A"),
    dict(proxyWallet=FUNDER, asset="21", conditionId=B, size=5, avgPrice=.3, redeemable=True, eventSlug=SLUG_B,
         outcome="Yes", title="B"),
    dict(proxyWallet=FUNDER, asset="41", conditionId=D, size=2, avgPrice=.5, redeemable=False, eventSlug=SLUG_A,
         outcome="Yes", title="D"),
]
MARKETS = {A: market(A, ["1", "0"]), B: market(B, ["0", "1"], slug=SLUG_B, title="17°C"),
           C: market(C, ["0.4", "0.6"], closed=False, slug="will-a-video-hit-1m-views", title=None,
                     source="https://youtube.com")}
FILLS = {"data": [{"market": C, "asset_id": "31", "match_time": "1790000000", "size": "20"},
                  {"market": A, "asset_id": "11", "match_time": "1790000100", "size": "10"}], "next_cursor": "LTE="}


def respond(req):
    parts = urlsplit(req.full_url)
    query = parse_qs(parts.query)
    if parts.path == "/positions":
        return POSITIONS if query["offset"] == ["0"] else []
    if parts.path == "/data/trades":
        assert query["maker_address"] == [FUNDER] and query["after"] == ["1789000000"]
        return FILLS
    if parts.path == "/markets":
        return [MARKETS[c] for c in query["condition_ids"] if c in MARKETS]
    raise AssertionError("unexpected endpoint " + parts.path)


def ledgers(tmp_path):
    root = tmp_path / "settlements" / "toronto"
    root.mkdir(parents=True)
    rows = [dict(event_slug=SLUG_A, revision_number=1, settlement_high=15, settlement_unit="C", winning_band="15°C",
                 reconciliation_status="mismatch"),
            dict(event_slug=SLUG_A, revision_number=2, settlement_high=16, settlement_unit="C", winning_band="16°C",
                 reconciliation_status="match", settlement_source="wu_history"),
            dict(event_slug=SLUG_B, revision_number=1, settlement_high=17, settlement_unit="C", winning_band="17 °C",
                 reconciliation_status="mismatch")]
    (root / "ledger.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
    events = tmp_path / "events.json"
    events.write_text(json.dumps({"locations": [{"location_id": "toronto", "event_slug_prefix": PREFIX, "active_events": [
        {"markets": [{"condition_id": A, "range_label": "16°C"}]}]}]}), encoding="utf-8")
    return tmp_path / "settlements", events


def test_settlement_joins_venue_resolution_with_wu_proxy_and_flags(tmp_path, guard):
    root, events = ledgers(tmp_path)
    t = wire(tmp_path, guard, FakeOpener(respond))
    reader = core.WalletReader(t, signature_type=3, settlement_root=root, events_config_path=events)
    result = reader.settlement("1789000000")
    by = {m["condition_id"]: m for m in result["markets"]}
    assert set(by) == {A, B, C, D}
    a = by[A]
    assert (a["resolution_state"], a["venue_winning_outcome"], a["venue_outcome_basis"]) == ("resolved", "Yes", "weather_gov")
    assert a["settlement_proxy"]["settlement_high"] == 16 and a["settlement_proxy"]["settlement_unit"] == "C"
    assert a["settlement_proxy"]["revision_number"] == 2 and a["settlement_proxy_status"] == "observed"
    assert a["proxy_says_this_band_won"] is True and a["venue_says_this_band_won"] is True and not a["disagreement"]
    assert a["held_positions"] == [dict(token_id="11", outcome="Yes", size="10", redeemable=True,
                                        terminal_price="1", unredeemed_winner=True)]
    assert a["recent_fills"] == 1
    b = by[B]
    assert b["proxy_says_this_band_won"] is True and b["venue_says_this_band_won"] is False and b["disagreement"]
    assert b["held_positions"][0]["terminal_price"] == "0" and not b["held_positions"][0]["unredeemed_winner"]
    c = by[C]
    assert c["resolution_state"] == "open" and c["held_positions"] == [] and c["recent_fills"] == 1
    assert c["settlement_proxy_status"] == "proxy_not_applicable" and c["venue_outcome_basis"] == "other"
    assert by[D]["resolution_state"] == "metadata_unavailable"
    assert result["flags"] == {"disagreements": [B], "unredeemed_winners": [A], "resolved_unreconciled": [B]}
    assert result["status"] == "PARTIAL" and result["counts"]["held_markets"] == 3
    assert result["plan"]["used_gets"] == len(t.opener.calls) == 3
    assert all(req.get_method() == "GET" for req, _ in t.opener.calls)


def test_missing_ledger_makes_resolved_holding_unreconciled_not_agreeing(tmp_path, guard):
    _, events = ledgers(tmp_path)
    t = wire(tmp_path, guard, FakeOpener(respond))
    reader = core.WalletReader(t, signature_type=3, settlement_root=tmp_path / "absent", events_config_path=events)
    result = reader.settlement("1789000000")
    a = next(m for m in result["markets"] if m["condition_id"] == A)
    assert a["settlement_proxy"] is None and a["settlement_proxy_status"] == "proxy_ledger_absent"
    assert a["proxy_says_this_band_won"] is None and not a["disagreement"]
    assert result["flags"]["resolved_unreconciled"] == [A, B] and result["flags"]["disagreements"] == []


def test_upstream_failures_are_partial_not_raised(tmp_path, guard):
    def failing(req):
        raise OSError("down")
    t = wire(tmp_path, guard, FakeOpener(failing))
    reader = core.WalletReader(t, signature_type=3, settlement_root=tmp_path, events_config_path=tmp_path / "none.json")
    result = reader.settlement("1789000000")
    assert result["status"] == "PARTIAL" and result["markets"] == []
    assert result["errors"] == {"positions": "positions_unavailable", "fills": "fills_unavailable"}


def test_closed_without_terminal_prices_is_not_resolved():
    assert settle.resolution_state({"closed": True}, [None, None]) == "closed_awaiting_terminal_price"
    assert settle.resolution_state({"closed": True}, [1, 1]) == "closed_awaiting_terminal_price"
    assert settle.resolution_state({}, None) == "metadata_unavailable"
    assert settle.band_key("16°C or below") == settle.band_key("16 °c OR below")
    assert settle.ledger_label("x", "../etc", "slug") == (None, "proxy_not_applicable")


def test_route_query_and_client_scope(guard):
    class Reader:
        def settlement(self, since):
            return {"since": since}
    token, allow = FIELDS["READER_TOKEN"], "192.168.1.30"
    headers = {"Authorization": "Bearer " + token}
    assert server.dispatch(Reader(), guard, token, allow, "GET", "/settlement?since=1789000000", allow, headers) == (
        200, {"since": "1789000000"})
    assert server.dispatch(Reader(), guard, token, allow, "GET", "/settlement?date=2026-09-01", allow, headers)[0] == 400
    assert server.dispatch(Reader(), guard, token, allow, "GET", "/settlement?since=abc", allow, headers)[0] == 503
    assert server.dispatch(Reader(), guard, token, allow, "POST", "/settlement", allow, headers)[0] == 405
    with pytest.raises(client.ClientError):
        client.read_account("summary", since="1789000000")
    with pytest.raises(client.ClientError) as refused:
        client.read_account("settlement", since="1789000000", config="missing.json")
    assert refused.value.reason == "config"


def test_ledger_over_the_old_64_mib_cap_streams_in_constant_memory(tmp_path):
    root = tmp_path / "settlements" / "toronto"
    root.mkdir(parents=True)
    path = root / "ledger.jsonl"
    filler = (json.dumps(dict(event_slug=PREFIX + "-january-1-2026", revision_number=1, settlement_high=1,
                              settlement_unit="C", padding="x" * 400)) + "\n").encode()
    chunk = filler * 4096
    with path.open("wb") as handle:
        handle.write((json.dumps(dict(event_slug=SLUG_A, revision_number=1, winning_band="15°C")) + "\n").encode())
        while handle.tell() < 70 * 1024 * 1024:
            handle.write(chunk)
        handle.write((json.dumps(dict(event_slug=SLUG_A, revision_number=2, winning_band="16°C")) + "\n").encode())
        handle.write((json.dumps(dict(event_slug=SLUG_B, revision_number=1, winning_band="17°C")) + "\n").encode())
    assert path.stat().st_size > 64 * 1024 * 1024
    tracemalloc.start()
    try:
        found, status = settle.ledger_labels(tmp_path / "settlements", "toronto", [SLUG_A, SLUG_B])
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert status is None
    assert (found[SLUG_A]["revision_number"], found[SLUG_A]["winning_band"]) == (2, "16°C")
    assert found[SLUG_B]["winning_band"] == "17°C"
    assert peak < 4 * settle.LEDGER_LINE_MAX_BYTES
    assert settle.ledger_label(tmp_path / "settlements", "toronto", SLUG_B)[0]["revision_number"] == 1
    assert settle.ledger_label(tmp_path / "settlements", "toronto", PREFIX + "-may-1-2026") == (None, "proxy_label_absent")


def test_overlong_ledger_lines_are_skipped_not_buffered(tmp_path, monkeypatch):
    monkeypatch.setattr(settle, "LEDGER_LINE_MAX_BYTES", 256)
    root = tmp_path / "toronto"
    root.mkdir()
    fits = json.dumps(dict(event_slug=SLUG_A, revision_number=1, pad=""))
    fits = json.dumps(dict(event_slug=SLUG_A, revision_number=1, pad="y" * (256 - len(fits))))
    assert len(fits) == 256
    long_row = json.dumps(dict(event_slug=SLUG_A, revision_number=9, pad="z" * 2000))
    (root / "ledger.jsonl").write_bytes(
        (fits + "\n" + long_row + "\n" + json.dumps(dict(event_slug=SLUG_B, revision_number=3)) + "\n" + long_row).encode())
    found, status = settle.ledger_labels(tmp_path, "toronto", [SLUG_A, SLUG_B, "Odd Slug"])
    assert status is None
    assert found[SLUG_A]["revision_number"] == 1 and found[SLUG_B]["revision_number"] == 3
    assert settle.ledger_labels(tmp_path, "toronto", [])[1] is None
    assert settle.ledger_labels(tmp_path, "missing", [SLUG_A]) == ({}, "proxy_ledger_absent")