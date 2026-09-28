"""110i acceptance fixtures. No real files, accounts, credentials or sockets."""
from copy import deepcopy
from decimal import Decimal as D
import json
import socket
from pathlib import Path

import pytest

from maker_core.contracts.portfolio import CAMPAIGNS_SCHEMA, SNAPSHOT_SCHEMA
from maker_core.evidence.journal import canonical_bytes
from maker_core.portfolio.ledger import build_book
from maker_core.portfolio.journal import append_book, verify_records
from maker_core.runtime.portfolio_report import main
from maker_core.venue.account_read import adapt_archive
from maker_core.venue.portfolio_client import read_archive

START = "2026-09-22T00:00:00+00:00"
NOW = "2026-09-26T01:00:00+00:00"
ACCOUNT = "0x" + "1" * 40


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("portfolio test attempted network")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "bind", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def campaigns():
    return dict(schema_version=CAMPAIGNS_SCHEMA, default_campaign="owner-discretionary",
        unattributed_cash_pusd="100", reconciliation_tolerance_pusd="0.000001",
        campaigns=[dict(id=name, start_utc=START, contributions=[dict(id=name + "-capital", at_utc=START,
            amount_pusd="135.218694" if name == "weather-maker" else "0")],
            bleed_limit_pusd="40" if name == "weather-maker" else None)
            for name in ("weather-maker", "youtube-maker", "owner-discretionary")],
        lot_overrides=[], rules=[dict(campaign="weather-maker", event_slug_prefix="highest-temperature-in-")])


def trade(event, asset, side, size, price, *, day=25, fee="0", slug=None):
    return dict(event_id=event, transaction_hash="tx-" + event, asset_id=asset, condition_id="condition-" + asset,
                event_slug=slug if slug is not None else "highest-temperature-in-" + asset,
                at_utc=f"2026-09-{day:02d}T12:00:00+00:00", side=side, size=str(size), price=str(price), fee_pusd=fee)


def position(asset, size, entry, *, resolved=False, terminal=None, slug=None):
    return dict(asset_id=asset, condition_id="condition-" + asset,
        event_slug=slug if slug is not None else "highest-temperature-in-" + asset,
        size=str(size), avg_price=str(entry), classification="resolved" if resolved else "live",
        redeemable=resolved, terminal_price=terminal, bid=str(entry), ask=str(entry))


def snapshot(trades=(), positions=(), cash="235.218694", now=NOW):
    return dict(schema_version=SNAPSHOT_SCHEMA, account_id=ACCOUNT, as_of_utc=now,
        cash_pusd=cash, positions=list(positions), trades=list(trades), positions_complete=True,
        history_complete=True, history_start_utc=START)


def test_owner_purchase_does_not_bleed_weather_then_weather_loss_is_realized(campaigns):
    # Miami cost 26.25, proceeds 13.50, explicit fee .55 => realized -13.30.
    events = [trade("miami-buy", "miami", "BUY", 75, ".35", day=23),
              trade("miami-sell", "miami", "SELL", 75, ".18", day=24, fee=".55"),
              trade("chicago-buy", "chicago", "BUY", 75, ".43", day=24),
              trade("youtube-buy", "youtube", "BUY", 140, ".72", slug="mrbeast-next-video")]
    held = [position("chicago", 75, ".43"), position("youtube", 140, ".72", slug="mrbeast-next-video")]
    value = snapshot(events, held, "88.868694")
    before = build_book([value], campaigns)
    weather = before["campaigns"]["weather-maker"]
    owner = before["campaigns"]["owner-discretionary"]
    assert before["status"] == "OBSERVED" and before["reconciliation"]["cash_difference_pusd"] == "0.000000"
    assert weather["status"] == "OBSERVED" and weather["bleed_limit_reached"] is False
    assert D(weather["contributed_capital_pusd"]) == D("135.218694")
    assert D(weather["realized_pnl_pusd"]) == D("-13.30")
    assert owner["open_lots"][0]["asset_id"] == "youtube" and owner["bleed_limit_pusd"] is None
    assert D(owner["cash_pusd"]) == D("-100.80")  # Shared cash financing is explicit, never charged to weather.
    value["positions"][0].update(classification="resolved", terminal_price="0")
    after = build_book([value], campaigns)
    assert D(after["campaigns"]["weather-maker"]["realized_pnl_pusd"]) == D("-45.55")
    assert after["campaigns"]["weather-maker"]["status"] == "BLEED_LIMIT"
    assert after["campaigns"]["owner-discretionary"]["status"] == "OBSERVED"


def test_unknown_terminal_only_affects_own_campaign_and_wallet(campaigns):
    value = snapshot([trade("buy", "weather", "BUY", 10, ".4")],
                     [position("weather", 10, ".4", resolved=True)], "231.218694")
    book = build_book([value], campaigns)
    assert book["status"] == "INCOMPLETE" and book["equity_pusd"] is None
    assert book["campaigns"]["weather-maker"]["unredeemed_terminal_value_pusd"] is None
    assert book["campaigns"]["weather-maker"]["status"] == "INCOMPLETE"
    assert book["campaigns"]["owner-discretionary"]["status"] == "OBSERVED"


def test_known_winner_and_redemption_never_double_count(campaigns):
    buy = trade("buy", "weather", "BUY", 10, ".4", day=24)
    held = snapshot([buy], [position("weather", 10, ".4", resolved=True, terminal="1")], "231.218694")
    first = build_book([held], campaigns)
    assert D(first["campaigns"]["weather-maker"]["realized_pnl_pusd"]) == 6
    assert D(first["campaigns"]["weather-maker"]["unredeemed_terminal_value_pusd"]) == 10
    redeemed = snapshot([buy, trade("redeem", "weather", "REDEEM", 10, "1")], [], "241.218694")
    second = build_book([redeemed], campaigns)
    assert second["equity_pusd"] == first["equity_pusd"]
    assert D(second["campaigns"]["weather-maker"]["realized_pnl_pusd"]) == 6
    assert D(second["campaigns"]["weather-maker"]["unredeemed_terminal_value_pusd"]) == 0
    redeemed["positions"] = held["positions"]
    assert build_book([redeemed], campaigns)["status"] == "INCOMPLETE"  # stale positive row


def test_override_is_per_acquisition_and_sell_consumes_fifo(campaigns):
    campaigns["lot_overrides"] = [dict(transaction_hash="tx-first", campaign="youtube-maker")]
    rows = [trade("first", "same", "BUY", 10, ".2", day=23, fee="1"),
            trade("second", "same", "BUY", 10, ".4", day=24),
            trade("sell", "same", "SELL", 15, ".6", fee="1.5")]
    book = build_book([snapshot(rows, [position("same", 5, ".4")], "235.718694")], campaigns)
    assert book["status"] == "OBSERVED"
    assert D(book["campaigns"]["youtube-maker"]["realized_pnl_pusd"]) == 2  # 4 less entry+exit fee
    assert D(book["campaigns"]["weather-maker"]["realized_pnl_pusd"]) == D(".5")
    assert book["campaigns"]["weather-maker"]["open_lots"][0]["transaction_hash"] == "tx-second"
    assert book["campaigns"]["youtube-maker"]["open_lots"] == []


def test_cash_mismatch_is_not_hidden_in_unattributed_cash(campaigns):
    book = build_book([snapshot(cash="234.218694")], campaigns)
    assert book["status"] == "INCOMPLETE"
    assert book["reconciliation"]["cash_difference_pusd"] == "-1.000000"
    assert book["unattributed_cash_pusd"] == "100"


@pytest.mark.parametrize("missing", ["fee", "history", "position", "mark", "cash"])
def test_missing_evidence_is_incomplete_not_zero(campaigns, missing):
    value = snapshot([trade("buy", "w", "BUY", 2, ".4")], [position("w", 2, ".4")], "234.418694")
    if missing == "fee":
        value["trades"][0]["fee_pusd"] = None
    elif missing == "history":
        value["history_complete"] = False
    elif missing == "position":
        value["positions"] = []
    elif missing == "cash":
        value["cash_pusd"] = None
    else:
        value["positions"][0]["ask"] = None
    book = build_book([value], campaigns)
    assert book["status"] == "INCOMPLETE"
    if missing != "cash":
        assert book["campaigns"]["weather-maker"]["pnl_pusd"] is None


def test_unmatched_lot_defaults_owner_but_missing_acquisition_stays_unknown(campaigns):
    value = snapshot(positions=[position("unknown", 2, ".5", slug="other")])
    book = build_book([value], campaigns)
    assert book["campaigns"]["owner-discretionary"]["status"] == "INCOMPLETE"
    assert book["campaigns"]["weather-maker"]["status"] == "OBSERVED"
    assert book["campaigns"]["owner-discretionary"]["open_lots"] == []


def test_rules_are_ordered_and_owner_has_no_bot_limit(campaigns):
    campaigns["rules"].insert(0, dict(condition_id="condition-w", campaign="youtube-maker"))
    value = snapshot([trade("buy", "w", "BUY", 2, ".4")], [position("w", 2, ".4")], "234.418694")
    assert build_book([value], campaigns)["campaigns"]["youtube-maker"]["open_lots"]
    campaigns["campaigns"][-1]["bleed_limit_pusd"] = "1"
    with pytest.raises(ValueError, match="bleed"):
        build_book([value], campaigns)


def test_rebuild_is_order_independent_and_deduplicates_repeated_snapshot_trades(campaigns):
    first = snapshot(now="2026-09-24T01:00:00+00:00")
    last = snapshot([trade("buy", "w", "BUY", 2, ".4")], [position("w", 2, ".4")], "234.418694")
    assert canonical_bytes(build_book([first, last], campaigns)) == canonical_bytes(build_book([last, first, last], campaigns))
    assert campaigns["campaigns"][0]["contributions"][0]["amount_pusd"] == "135.218694"


def test_conflicting_trade_history_is_refused_as_complete(campaigns):
    first = snapshot([trade("buy", "w", "BUY", 2, ".4")], [position("w", 2, ".4")], "234.418694")
    changed = deepcopy(first)
    changed["trades"][0]["price"] = ".3"
    assert "conflicting_trade_record" in build_book([first, changed], campaigns)["reasons"]


def test_same_asset_timestamp_tie_cannot_claim_proven_fifo(campaigns):
    rows = [trade("first", "w", "BUY", 2, ".2"), trade("second", "w", "BUY", 2, ".4")]
    book = build_book([snapshot(rows, [position("w", 4, ".3")], "234.018694")], campaigns)
    assert "ambiguous_trade_order" in book["campaigns"]["weather-maker"]["reasons"]
    assert book["status"] == "INCOMPLETE"
    assert book["campaigns"]["weather-maker"]["realized_pnl_pusd"] is None


@pytest.mark.parametrize("activity", [None, {}, [None]])
def test_malformed_activity_preserves_positions_and_invalidates_history(activity):
    archive = archive_fixture()
    archive["trades"]["account_activity"] = activity
    neutral = adapt_archive(archive)
    assert neutral["positions"] and not neutral["history_complete"]


def test_journal_chain_duplicate_tamper_and_existing_lock(tmp_path, campaigns):
    first = build_book([snapshot()], campaigns)
    out = tmp_path / "out"
    receipt = append_book(out, first)
    before = Path(receipt["path"]).read_bytes()
    with pytest.raises(FileExistsError):
        append_book(out, first)
    assert Path(receipt["path"]).read_bytes() == before
    second = build_book([snapshot(cash="230")], campaigns)
    append_book(out, second)
    records, last = verify_records(out)
    assert len(records) == 2 and records[1]["previous_sha256"] == receipt["sha256"] and last
    (out / ".writer.lock").write_text("another writer")
    with pytest.raises(FileExistsError):
        append_book(out, second)
    assert (out / ".writer.lock").read_text() == "another writer"
    (out / "00000000.json").write_bytes(before.replace(b'OBSERVED', b'TAMPERED'))
    with pytest.raises(ValueError, match="chain"):
        verify_records(out)


def archive_fixture():
    return dict(account_id=ACCOUNT, captured_at_utc=NOW,
        summary=dict(cash_pusd="234.418694", positions=[dict(token_id="w", condition_id="condition-w",
            event_slug="highest-temperature-in-w", size="2", avg_price=".4", bid=".4", ask=".4",
            classification="live")], resolved_positions=[], resolved_count=0),
        trades=dict(history_complete=True, history_start_utc=START, account_activity=[dict(
            id="buy", transactionHash="tx-buy", proxyWallet=ACCOUNT, timestamp="2026-09-25T12:00:00Z",
            type="TRADE", side="BUY", asset="w", conditionId="condition-w",
            eventSlug="highest-temperature-in-w", size="2", price=".4", fee_pusd="0")]))


def test_reader_adapter_whitelists_and_retains_unknown_fees(campaigns):
    archive = archive_fixture()
    archive["secret"] = "must-not-copy"
    neutral = adapt_archive(archive)
    assert "must-not-copy" not in json.dumps(neutral)
    assert build_book([neutral], campaigns)["status"] == "OBSERVED"
    archive["trades"]["account_activity"][0].pop("fee_pusd")
    assert build_book([adapt_archive(archive)], campaigns)["status"] == "INCOMPLETE"
    archive["summary"]["resolved_count"] = 1
    assert adapt_archive(archive)["positions_complete"] is False


@pytest.mark.parametrize("fault", ["foreign", "unsupported", "missing_hash"])
def test_adapter_unknown_activity_does_not_claim_complete(fault):
    archive = archive_fixture()
    row = archive["trades"]["account_activity"][0]
    if fault == "foreign":
        row["proxyWallet"] = "other"
    elif fault == "unsupported":
        row["type"] = "SPLIT"
    else:
        row.pop("transactionHash")
    assert adapt_archive(archive)["history_complete"] is False


def test_cli_archive_rebuild_and_overwrite_refusal(tmp_path, campaigns, capsys):
    inputs = tmp_path / "snapshots"
    inputs.mkdir()
    (inputs / "record.json").write_text(json.dumps(archive_fixture()))
    config = tmp_path / "campaigns.json"
    config.write_text(json.dumps(campaigns))
    args = ["report", "--snapshots", str(inputs), "--campaigns", str(config), "--out", str(tmp_path / "first")]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert main([*args[:-1], str(tmp_path / "second")]) == 0
    assert json.loads(capsys.readouterr().out)["book_sha256"] == first["book_sha256"]
    assert main(args) == 1
    assert json.loads(capsys.readouterr().out) == {"error": "portfolio_report_failed"}


def test_lan_client_fixed_gets_and_no_secret_echo():
    token = "ab" * 32
    class Reply:
        status = 200
        def __init__(self, request):
            self.request = request
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def geturl(self):
            return self.request.full_url
        def read(self, count):
            return json.dumps(dict(account_id=ACCOUNT, captured_at_utc=NOW)).encode()
    class Opener:
        calls = []
        def open(self, request, timeout):
            assert request.get_method() == "GET" and timeout == 20 and request.data is None
            self.calls.append(request.full_url)
            return Reply(request)
    opener = Opener()
    config = dict(url="http://192.168.1.106:8765", token=token)
    read_archive(config["url"], config, 0, opener=opener)
    assert opener.calls == [config["url"] + "/summary?include_resolved=true", config["url"] + "/trades?since=0"]
    for url in ("http://example.com:8765", "http://8.8.8.8:8765", config["url"] + "/orders"):
        with pytest.raises(ValueError, match="portfolio_reader_unavailable"):
            read_archive(url, config, 0, opener=opener)
    assert len(opener.calls) == 2
