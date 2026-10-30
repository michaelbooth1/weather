"""Lane L3 WS T+1 price forward recorder (tools/research/t1_price_forward_recorder.py).

Guards: the URL allowlist (only GET a Gamma event by slug and POST a CLOB book batch of token ids; no query, no
credentials in the URL, no other host or path), the Gamma "Yes" entry chosen by label not position, the CLOB best
bid/ask taken as max/min over non-empty levels, the full-ladder sum check, target dates from each market's local date
(T+1 and T+2), one fsynced cycle append with rows_sha256, complete/incomplete cycles with reasons, the once-per-slot
rule, missed slots recorded as gaps, the day manifest, top-of-hour-only mode, and the pause and STOP files.
No network: an in-memory fake serves Gamma events and CLOB books.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import sys

import pytest

from weather.paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("t1_price_forward_recorder",
                                               REPO_ROOT / "tools/research/t1_price_forward_recorder.py")
rc = importlib.util.module_from_spec(_spec)
sys.modules["t1_price_forward_recorder"] = rc
_spec.loader.exec_module(rc)

UTC = dt.timezone.utc
MARKETS = {"toronto": ("highest-temperature-in-toronto-on", "America/Toronto"),
           "nyc": ("highest-temperature-in-nyc-on", "America/New_York")}


def market(i, yes, outcomes=("Yes", "No")):
    no = "" if yes is None else str(round(1 - yes, 4))
    yes = "" if yes is None else str(yes)
    prices = [yes, no] if outcomes[0] == "Yes" else [no, yes]
    tokens = [str(10 ** 20 + 2 * i), str(10 ** 20 + 2 * i + 1)]
    if outcomes[0] != "Yes":
        tokens = tokens[::-1]
    return {"id": str(500 + i), "conditionId": "0x" + f"{i:064x}", "groupItemTitle": f"{60 + i}-{61 + i}F",
            "outcomes": json.dumps(list(outcomes)), "outcomePrices": json.dumps(prices),
            "clobTokenIds": json.dumps(tokens), "active": True, "closed": False, "acceptingOrders": True}


class Fake:
    def __init__(self, ladders=None, missing=(), book_status=200):
        self.ladders = ladders or {}
        self.missing, self.book_status = set(missing), book_status
        self.calls, self.used, self.requests = [], 0, 0

    def request(self, method, url, body=None):
        rc.check_url(method, url, body)
        self.calls.append((method, url, body))
        self.requests += 1
        if method == "GET":
            slug = url.rsplit("/", 1)[1]
            if slug in self.missing:
                return rc.Resp(404, b"{}", {})
            yes = self.ladders.get(slug, [0.1, 0.2, 0.4, 0.3])
            ev = {"id": "ev-" + slug[-12:], "slug": slug, "markets": [market(i, y) for i, y in enumerate(yes)]}
            return rc.Resp(200, json.dumps(ev).encode(), {})
        if self.book_status != 200:
            return rc.Resp(self.book_status, b"[]", {})
        books = [{"asset_id": x["token_id"], "timestamp": "1761868800000",
                  "bids": [{"price": "0.10", "size": "5"}, {"price": "0.12", "size": "7"}, {"price": "0.2", "size": "0"}],
                  "asks": [{"price": "0.30", "size": "3"}, {"price": "0.25", "size": "4"}]} for x in body]
        return rc.Resp(200, json.dumps(books).encode(), {})


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def make(tmp_path, fake=None, t=dt.datetime(2026, 10, 31, 3, 0, 20, tzinfo=UTC), **kw):
    clock = Clock(t)
    rec = rc.Recorder(tmp_path / "out", fake or Fake(), markets=MARKETS, clock=clock, sleep=lambda s: None,
                      min_free_gb=0.0, **kw)
    return rec, clock


def rows(rec, day="20261031"):
    return rc.read_jsonl(rec.out / day / "prices.jsonl")


@pytest.mark.parametrize("method,url,body", [
    ("GET", "https://gamma-api.polymarket.com/events/slug/highest-temperature-in-nyc-on-november-1-2026?x=1", None),
    ("GET", "https://gamma-api.polymarket.com/events?slug=highest-temperature-in-nyc-on-november-1-2026", None),
    ("GET", "http://gamma-api.polymarket.com/events/slug/highest-temperature-in-nyc-on-november-1-2026", None),
    ("GET", "https://user:pw@gamma-api.polymarket.com/events/slug/highest-temperature-in-nyc-on-november-1-2026", None),
    ("GET", "https://clob.polymarket.com/book", None),
    ("POST", "https://clob.polymarket.com/order", [{"token_id": "1" * 20}]),
    ("POST", "https://clob.polymarket.com/books", [{"token_id": "1" * 20, "side": "BUY"}]),
    ("POST", "https://clob.polymarket.com/books", [{"token_id": "1" * 20}] * 51),
    ("POST", "https://clob.polymarket.com/books", []),
    ("GET", "https://gamma-api.polymarket.us/events/slug/highest-temperature-in-nyc-on-november-1-2026", None),
    ("DELETE", "https://clob.polymarket.com/books", [{"token_id": "1" * 20}]),
])
def test_allowlist_refuses_everything_but_the_two_public_reads(method, url, body):
    with pytest.raises(rc.Refused):
        rc.check_url(method, url, body)


def test_allowlist_accepts_the_two_public_reads():
    rc.check_url("GET", "https://gamma-api.polymarket.com/events/slug/highest-temperature-in-nyc-on-november-1-2026",
                 None)
    rc.check_url("POST", "https://clob.polymarket.com/books", [{"token_id": "1" * 20}])


def test_yes_is_chosen_by_label_and_book_best_levels():
    ev = {"markets": [market(0, 0.3, outcomes=("No", "Yes"))]}
    (band,) = rc.parse_event(ev)
    assert band["yes"] == 0.3 and band["yes_token"] == str(10 ** 20)
    assert rc.best_levels({"bids": [{"price": "0.1", "size": "1"}, {"price": "0.12", "size": "2"},
                                    {"price": "0.5", "size": "0"}],
                           "asks": [{"price": "0.3", "size": "1"}, {"price": "0.25", "size": "2"}]}) == (0.12, 2.0, 0.25, 2.0)
    assert rc.best_levels({"bids": [], "asks": []}) == (None, None, None, None)


def test_event_slug_matches_the_repository_rule():
    from weather.market.market_config import event_slug_for_date

    for d in (dt.date(2026, 11, 1), dt.date(2026, 12, 31), dt.date(2027, 1, 9)):
        assert rc.event_slug("highest-temperature-in-nyc-on", d) == event_slug_for_date(d, "nyc")


def test_cycle_records_full_ladders_for_t1_and_t2_with_sha(tmp_path):
    rec, _ = make(tmp_path)  # 03:00Z = 23:00 local on 10-30 in both zones
    cycle = rec.step()
    assert cycle["ran"] and cycle["complete"]
    got = rows(rec)
    events, (cyc,) = got[:-1], got[-1:]
    assert [(r["market"], r["horizon"], r["target_date"]) for r in events] == [
        ("toronto", 1, "2026-10-31"), ("toronto", 2, "2026-11-01"), ("nyc", 1, "2026-10-31"), ("nyc", 2, "2026-11-01")]
    r = events[0]
    assert r["event_slug"] == "highest-temperature-in-toronto-on-october-31-2026"
    assert r["n_bands"] == 4 and r["ladder_complete"] and r["sum_in_range"] and r["yes_sum"] == 1.0
    assert r["gamma_received_utc"] and r["books_received_utc"] and r["event_id"]
    b = r["bands"][0]
    assert b["condition_id"].startswith("0x") and b["best_bid"] == 0.12 and b["best_ask"] == 0.25
    assert cyc["kind"] == "cycle" and cyc["complete"] and cyc["top_of_hour"] and cyc["events_complete"] == 4
    body = "".join(json.dumps(x, sort_keys=True) + "\n" for x in events).encode()
    assert cyc["rows_sha256"] == hashlib.sha256(body).hexdigest()


def test_incomplete_cycle_lists_reasons(tmp_path):
    fake = Fake(ladders={"highest-temperature-in-nyc-on-october-31-2026": [0.5, None, 0.5]},
                missing={"highest-temperature-in-toronto-on-november-1-2026"})
    rec, _ = make(tmp_path, fake)
    rec.step()
    cyc = rows(rec)[-1]
    assert not cyc["complete"]
    assert "toronto+2:gamma_http_404" in cyc["reasons"] and "nyc+1:ladder_incomplete" in cyc["reasons"]


def test_book_failure_keeps_gamma_prices(tmp_path):
    rec, _ = make(tmp_path, Fake(book_status=500))
    rec.step()
    r = rows(rec)[0]
    assert r["ladder_complete"] and r["book_status"] == "http_500" and r["n_book_two_sided"] == 0


def test_slot_runs_once_then_missed_slots_are_gaps_and_day_closes(tmp_path):
    rec, clock = make(tmp_path)
    assert rec.step()["ran"]
    clock.t += dt.timedelta(minutes=3)
    assert not rec.step()["ran"]  # same slot, already done
    clock.t = dt.datetime(2026, 10, 31, 3, 59, tzinfo=UTC)  # 03:15, 03:30 and 03:45 were never run
    rec.step()
    gaps = rc.read_jsonl(rec.out / "gaps.jsonl")
    assert [g["slot_utc"] for g in gaps] == ["2026-10-31T03:15:00Z", "2026-10-31T03:30:00Z"]
    clock.t = dt.datetime(2026, 11, 1, 0, 1, tzinfo=UTC)
    rec.step()
    man = json.loads((rec.out / "20261031" / "manifest.json").read_text())
    assert man["cycles"] == 1 and man["top_of_hour_complete"] == 1 and man["top_of_hour_missing"] == 23


def test_restart_does_not_repeat_a_done_slot_and_closes_old_days(tmp_path):
    rec, _ = make(tmp_path)
    rec.step()
    rec2, clock2 = make(tmp_path)
    assert not rec2.step()["ran"]
    rec3, _ = make(tmp_path, t=dt.datetime(2026, 11, 1, 5, 0, 5, tzinfo=UTC))
    rec3.step()
    assert (rec3.out / "20261031" / "manifest.json").exists()


def test_late_slot_and_quarter_hours(tmp_path):
    rec, clock = make(tmp_path, t=dt.datetime(2026, 10, 31, 3, 11, tzinfo=UTC))
    assert not rec.step()["ran"]  # beyond the 10-minute grace: never backfilled
    rec2, _ = make(tmp_path / "b", t=dt.datetime(2026, 10, 31, 3, 15, 5, tzinfo=UTC), quarter_hours=False)
    assert not rec2.step()["ran"]
    rec3, _ = make(tmp_path / "c", t=dt.datetime(2026, 10, 31, 3, 15, 5, tzinfo=UTC))
    assert rec3.step()["ran"]
    assert rows(rec3)[-1]["top_of_hour"] is False


def test_pause_and_stop_files(tmp_path):
    rec, clock = make(tmp_path)
    rec.pause_file.write_text("")
    assert not rec.step()["ran"]
    rec.pause_file.unlink()
    clock.t = dt.datetime(2026, 10, 31, 4, 0, 5, tzinfo=UTC)
    rec.stop_file.write_text("")
    rec.step()
    cyc = rows(rec)[-1]
    assert not cyc["complete"] and "stop_file" in cyc["reasons"] and cyc["events_rows"] == 0
    kinds = [g["gap"] for g in rc.read_jsonl(rec.out / "gaps.jsonl")]
    assert kinds[:2] == ["pause_start", "pause_end"]
    rec.run(poll_s=0, max_steps=3)
    assert json.loads((rec.out / "status.json").read_text())["state"] == "stopped_by_file"


def test_hourly_ceiling_stops_requests(tmp_path):
    fake = Fake()
    rec, _ = make(tmp_path, fake, hourly_requests=3)
    rec.step()
    assert fake.requests == 3
    assert not rows(rec)[-1]["complete"]


def test_refuses_candidate_registry_override(monkeypatch):
    monkeypatch.setenv("WEATHER_MARKET_REGISTRY", "config/candidate_markets.json")
    with pytest.raises(SystemExit):
        rc.markets_from_registry()


def test_registry_markets_are_the_built_ins(monkeypatch):
    monkeypatch.delenv("WEATHER_MARKET_REGISTRY", raising=False)
    got = rc.markets_from_registry()
    assert tuple(got) == rc.MARKETS
    assert got["toronto"][1] == "America/Toronto" and got["denver"][0].startswith("highest-temperature-in-denver")


def test_module_imports_nothing_credential_bearing():
    import ast

    src = (REPO_ROOT / "tools/research/t1_price_forward_recorder.py").read_text(encoding="utf-8")
    mods = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
    assert mods <= {"__future__", "argparse", "datetime", "hashlib", "json", "math", "os", "re", "shutil", "sys",
                    "time", "traceback", "pathlib", "zoneinfo", "ctypes", "msvcrt", "fcntl", "ssl", "http.client",
                    "urllib.parse", "weather.market.market_registry"}, mods
    for banned in ("dotenv", "py_clob_client", "Authorization", "POLY_", "private_key", "api_key"):
        assert banned not in src
