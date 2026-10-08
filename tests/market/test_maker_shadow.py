"""Weather shadow CLI: no-network fixture run, 88a fixture panel scoring, embargo and import closure.

Guards: weather maker shadow CLI no-network run, 88a scoring embargo and import closure
  (docs/operations/maker-shadow-runner.md, Commands and Nightly scoring against 88a).
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.runtime import guard_latch
from maker_core.venue import public_feed
from weather.market import maker_shadow
from weather.market.maker_evidence_store import EvidenceStore
from weather.market.maker_shadow_panel import EMBARGOED_UTC_DAYS, MakerEvidencePanel, embargo_reason
from weather.market.market_config import event_slug_for_date

from tests.maker_core.fixtures.shadow_rig import (CAPS, CONDITION, NO, NOW, PAPER_POLICY, POLICY, YES, data_print,
                                                  public_book, reward_record)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("shadow test attempted network")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))
    return str(path)


def setup(tmp_path, *, bleed_limit="5", prints=()):
    guard_latch.initialize(tmp_path / "latch", NOW)
    guard = {"policy": PAPER_POLICY, "latch_dir": str(tmp_path / "latch"), "pause_file": str(tmp_path / "PAUSE")}
    paper = {"starting_cash_pusd": "100", "bleed_limit_pusd": bleed_limit, "fill_rule": "at_price"}
    config = {"schema_version": maker_shadow.CONFIG_SCHEMA, "profile": "informed-v0", "hazard_per_minute": 0.001,
              "caps": CAPS, "markets": ["nyc"], "horizons": [1, 2], "max_conditions": 4, "guard": guard,
              "paper": paper}
    nyc = next(s for s in maker_shadow.all_specs() if s.id == "nyc")
    local = NOW.astimezone(nyc.tz).date()
    slugs = [event_slug_for_date(local + timedelta(days=h), "nyc") for h in (1, 2)]
    event = {"id": "77", "slug": slugs[0], "negRisk": True, "markets": [
        {"conditionId": CONDITION, "active": True, "closed": False, "enableOrderBook": True,
         "clobTokenIds": json.dumps([YES, NO]), "outcomes": json.dumps(["Yes", "No"]),
         "orderPriceMinTickSize": 0.01, "orderMinSize": 5, "endDate": "2026-09-30T16:00:00Z",
         "bestBid": 0.49, "bestAsk": 0.51, "clobRewards": [{"rewardsDailyRate": 100}]},
        {"conditionId": "0x" + "b" * 64, "active": True, "closed": True, "clobTokenIds": "[]", "outcomes": "[]"}]}
    replies = {public_feed.events_url(slugs): [event], public_feed.book_url(YES): public_book(YES),
               public_feed.book_url(NO): public_book(NO, bids=(("0.49", "100"),), asks=(("0.51", "100"),)),
               public_feed.rewards_url(CONDITION): {"data": [reward_record()], "next_cursor": "LTE="},
               public_feed.trades_url(CONDITION): list(prints)}
    fixture = {"schema_version": maker_shadow.FIXTURE_SCHEMA, "clock_start_utc": NOW.isoformat(), "replies": replies}
    return write(tmp_path / "config.json", config), write(tmp_path / "fixture.json", fixture)


def run_offline(tmp_path, minutes=3, **kw):
    config, fixture = setup(tmp_path, **kw)
    code = maker_shadow.main(["run", "--config", config, "--offline-fixture", fixture, "--minutes", str(minutes),
                              "--output-root", str(tmp_path / "tapes")])
    assert code == 0
    return sorted((tmp_path / "tapes").glob("*.tape.jsonl"))


def test_offline_fixture_run_writes_sealed_per_minute_tape(tmp_path, capsys):
    tapes = run_offline(tmp_path)
    summary = json.loads(capsys.readouterr().out)
    assert summary["mode"] == "offline_fixture" and summary["minutes"] == 3 and len(summary["sealed"]) == 1
    rows = [json.loads(line) for line in tapes[0].read_text().splitlines()]
    events = [r["event"] for r in rows]
    assert events == ["opened", "universe", "minute", "minute", "minute", "terminal"]
    universe = rows[1]
    assert universe["selected"] == [CONDITION] and universe["refused"] == {"not_open": 1}
    assert len(universe["events_missing"]) == 1
    first = rows[2]["conditions"][0]
    assert first["decision"]["action"] == "QUOTE" and [g["action"] for g in first["gate"]] == ["ALLOW", "ALLOW"]
    assert first["inputs"]["market"]["native_unit"] == "F" and first["horizon_days"] == 1
    assert rows[0]["scope"]["fair_value"].startswith("unavailable:")


def test_offline_run_paper_book_fills_and_allows(tmp_path):
    # A print at the bid fills 30 YES at 0.48 under the at-price rule; the mark stays at the 0.50 mid,
    # so paper P&L is +0.6 and the guard keeps allowing. The bleed HALT path is in test_shadow.py.
    prints = [data_print(YES, NOW + timedelta(seconds=20), "0.48", 30)]
    tapes = run_offline(tmp_path, minutes=3, prints=prints)
    rows = [json.loads(line) for line in tapes[0].read_text().splitlines()]
    minutes = [r for r in rows if r["event"] == "minute"]
    assert all(m["guard"]["action"] == "ALLOW" for m in minutes)
    assert minutes[1]["paper"]["fills"][0]["size"] == "30.0" and minutes[2]["paper"]["pnl_pusd"] == "0.600"
    assert rows[0]["scope"]["guard_book"] == "paper_campaign_book"


def test_stop_file_and_config_refusals(tmp_path, capsys):
    config, fixture = setup(tmp_path)
    (tmp_path / "STOP").write_text("x")
    assert maker_shadow.main(["run", "--config", config, "--offline-fixture", fixture, "--minutes", "1",
                              "--stop-file", str(tmp_path / "STOP")]) == 2
    assert "stop_file_present_at_start" in capsys.readouterr().err
    base = json.loads(Path(config).read_text())
    for change in ({"guard": {**base["guard"], "wallet_book": str(tmp_path / "book.json")}},
                   {"guard": {**base["guard"], "campaigns": str(tmp_path / "campaigns.json")}}):
        with pytest.raises(ValueError, match="shadow_mode_refuses_real_wallet_book"):
            maker_shadow.load_config(write(tmp_path / "wallet.json", {**base, **change}))
    with pytest.raises(ValueError, match="guard_policy_must_name_paper_campaign"):
        maker_shadow.load_config(write(tmp_path / "pol.json", {**base, "guard": {**base["guard"], "policy": POLICY}}))
    for change in ({"hazard_per_minute": None}, {"paper": {**base["paper"], "fill_rule": "midpoint"}},
                   {"paper": {**base["paper"], "bleed_limit_pusd": "500"}}, {"paper": None}, {"markets": ["atlantis"]}, {"profile": "aggressive"},
                   {"caps": {"cash": "1"}}, {"extra": 1}, {"adverse_markout": 0.001}, {"horizons": [3]}):
        bad = write(tmp_path / "bad.json", {**base, **change})
        with pytest.raises(ValueError):
            maker_shadow.load_config(bad)
    assert maker_shadow.main(["run", "--config", config, "--offline-fixture", fixture]) == 2


def write_panel(root, *, day_start=NOW, minutes=40):
    clock = {"now": day_start}
    store = EvidenceStore(root, clock=lambda: clock["now"])
    for n in range(minutes):
        clock["now"] = day_start + timedelta(minutes=n, seconds=5)
        store.record("books", json.dumps([public_book(YES), public_book(NO)]).encode())
        if n == 0:
            clock["now"] = day_start + timedelta(seconds=40)
            ms = int((day_start + timedelta(seconds=30)).timestamp() * 1000)
            trade = {"event_type": "last_trade_price", "asset_id": YES, "price": "0.47", "size": "10",
                     "side": "SELL", "timestamp": str(ms), "market": CONDITION}
            store.record("trades", json.dumps([trade, trade]).encode())  # duplicate print counts once
    store.seal()


def test_nightly_score_against_88a_fixture_panel(tmp_path, capsys):
    run_offline(tmp_path, minutes=3)
    capsys.readouterr()
    write_panel(tmp_path / "maker_evidence")
    out = tmp_path / "report.json"
    code = maker_shadow.main(["score", "--day", "2026-09-28", "--tape-root", str(tmp_path / "tapes"),
                              "--maker-evidence-root", str(tmp_path / "maker_evidence"), "--out", str(out)])
    assert code == 0, capsys.readouterr()
    report = json.loads(out.read_text())
    assert report["label"] == "DIAGNOSTIC_NOT_A_VERDICT" and report["agreement"]["status"] == "PASS"
    assert report["panel"]["segments_read"] == 1 and report["panel"]["assets_covered"] == 2
    strict = report["strata"]["gated"]["rules"]["strictly_through"]
    assert strict["fills"] == 1 and strict["shares"] == "10" and strict["spread_pusd"] == "0.20"
    assert strict["horizons"]["30"]["missing"] == 0
    with pytest.raises(FileExistsError):
        maker_shadow.main(["score", "--day", "2026-09-28", "--tape-root", str(tmp_path / "tapes"),
                           "--maker-evidence-root", str(tmp_path / "maker_evidence"), "--out", str(out)])


def test_panel_rejects_changed_evidence_and_skips_unsealed(tmp_path):
    write_panel(tmp_path / "me", minutes=2)
    segment = next((tmp_path / "me" / "2026-09-28").iterdir())
    (tmp_path / "me" / "2026-09-28" / "15-0123456789ab").mkdir()
    panel = MakerEvidencePanel(tmp_path / "me", "2026-09-28", {YES})
    assert panel.summary["unsealed_segments_skipped"] == ["15-0123456789ab"]
    assert panel.mid(YES, NOW + timedelta(minutes=1, seconds=10)) == panel.mid(YES, NOW + timedelta(seconds=6))
    assert panel.mid(YES, NOW + timedelta(minutes=10)) is None  # older than 120 s
    book_file = next(segment.glob("book-111.jsonl"))
    book_file.write_bytes(book_file.read_bytes().replace(b"0.49", b"0.39"))
    with pytest.raises(ValueError, match="differs_from_manifest"):
        MakerEvidencePanel(tmp_path / "me", "2026-09-28", {YES})


@pytest.mark.parametrize("day", ["2026-09-30", "2026-10-14", "2026-10-15", "2026-10-30", "2026-11-13"])
def test_embargoed_days_refused_before_any_read(tmp_path, capsys, day):
    assert embargo_reason(day)
    code = maker_shadow.main(["score", "--day", day, "--tape-root", str(tmp_path / "missing"),
                              "--maker-evidence-root", str(tmp_path / "missing")])
    assert code == 2 and json.loads(capsys.readouterr().out)["refused"] == "embargoed_utc_day"


def test_embargo_windows_and_open_day(tmp_path, capsys):
    assert embargo_reason("2026-09-29") is None and embargo_reason("2026-11-14") is None
    assert all(start <= end for start, end, _ in EMBARGOED_UTC_DAYS)
    today = max(datetime.now(timezone.utc).date().isoformat(), "2026-11-14")
    assert maker_shadow.main(["score", "--day", today, "--tape-root", str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out)["refused"] == "utc_day_not_closed"


def test_cli_import_closure_has_no_order_client_or_credentials():
    code = ("import sys, json, weather.market.maker_shadow, weather.market.maker_shadow_panel; "
            "print(json.dumps(sorted(sys.modules)))")
    env = dict(os.environ, PYTHONPATH=str(Path("src").resolve()))
    loaded = set(json.loads(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                                           env=env, cwd=Path.cwd()).stdout))
    forbidden = {"py_clob_client", "eth_account", "web3", "dotenv", "websocket", "requests",
                 "maker_core.runtime.credentials", "maker_core.venue.portfolio_client",
                 "weather.market.mm_exchange", "weather.market.mm_official_adapter",
                 "weather.market.mm_official_transport", "weather.market.polymarket_client",
                 "weather.market.mm_credentials", "weather.market.live_sdk_overlay",
                 "weather.market.maker_evidence_capture", "weather.market.wallet_reader"}
    assert not {m for m in loaded if m in forbidden or m.split(".")[0] in forbidden}
