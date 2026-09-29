import io
import json
import subprocess
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from weather.market import reward_scan as scan

NOW = datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc)
COND_A = "0x" + "a" * 64
COND_B = "0x" + "b" * 64
COND_X = "0x" + "c" * 64
YES_A, NO_A, YES_B, NO_B, YES_X, NO_X = "111", "112", "221", "222", "331", "332"


def events(end="2026-09-29T12:00:00Z"):
    def market(condition, yes, no, **extra):
        return dict(condition_id=condition, question="q " + condition[:6], active=True, closed=False,
                    enable_order_book=True, outcome_tokens={"Yes": yes, "No": no}, **extra)
    return {"generated_at_utc": "2026-09-28T04:00:00+00:00", "locations": [
        {"location_id": "amsterdam", "active_events": [
            {"event_slug": "ams-sep-29", "event_date": "2026-09-29", "end_date": end,
             "markets": [market(COND_A, YES_A, NO_A), market(COND_B, YES_B, NO_B)]},
            {"event_slug": "ams-sep-27", "event_date": "2026-09-27", "end_date": "2026-09-27T12:00:00Z",
             "markets": [market("0x" + "d" * 64, "441", "442")]}]}]}


def reward_page(condition, rate=10.0, spread=4.5, min_size=50):
    return {"data": [{"condition_id": condition, "rewards_max_spread": spread, "rewards_min_size": min_size,
                      "rewards_config": [{"start_date": "2026-09-01", "end_date": "2026-10-31", "rate_per_day": rate},
                                         {"start_date": "2026-08-01", "end_date": "2026-08-31", "rate_per_day": 99}]}],
            "next_cursor": "LTE="}


def book(condition, token, bids, asks):
    return {"market": condition, "asset_id": token, "tick_size": "0.01",
            "bids": [{"price": str(p), "size": str(s)} for p, s in bids],
            "asks": [{"price": str(p), "size": str(s)} for p, s in asks]}


FIXTURES = {
    ("/rewards/markets/" + COND_A, ""): reward_page(COND_A),
    ("/book", YES_A): book(COND_A, YES_A, [(0.40, 100), (0.39, 20), (0.35, 60)], [(0.44, 80), (0.47, 70), (0.60, 500)]),
    ("/rewards/markets/" + COND_B, ""): reward_page(COND_B, rate=0),
    ("/rewards/markets/" + COND_X, ""): reward_page(COND_X, rate=5, spread=3, min_size=20),
    ("/book", YES_X): book(COND_X, YES_X, [(0.03, 100)], [(0.05, 100)]),
}


class Response(io.BytesIO):
    def __init__(self, url, payload, status=200):
        super().__init__(json.dumps(payload).encode())
        self.url, self.status = url, status

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Opener:
    def __init__(self, fixtures=FIXTURES):
        self.fixtures, self.calls = fixtures, []

    def open(self, request, timeout):
        assert request.get_method() == "GET"
        assert not any(k.lower().startswith(("poly", "authorization")) for k in request.headers)
        parts = urlsplit(request.full_url)
        self.calls.append(request.full_url)
        query = parse_qs(parts.query)
        if parts.netloc == "gamma-api.polymarket.com":
            return Response(request.full_url, [{"conditionId": COND_X, "clobTokenIds": json.dumps([YES_X, NO_X]),
                                                "outcomes": json.dumps(["Over", "Under"]), "active": True,
                                                "closed": False, "slug": "yt-views", "endDate": "2026-10-02T00:00:00Z"}])
        key = (parts.path, query.get("token_id", [""])[0])
        return Response(request.full_url, self.fixtures[key])


class NoSocket:
    def open(self, request, timeout):
        raise AssertionError("socket opened")


def reader(opener=None, **kwargs):
    kwargs.setdefault("min_interval", 0.05)
    return scan.PublicReader(opener=opener or Opener(), sleep=lambda s: None, **kwargs)


@pytest.mark.parametrize("method,host,path,params", [
    ("POST", scan.CLOB, "/book", {"token_id": "1"}),
    ("DELETE", scan.CLOB, "/book", {"token_id": "1"}),
    ("GET", scan.CLOB, "/order", {}),
    ("GET", scan.CLOB, "/orders", {}),
    ("GET", scan.CLOB, "/balance-allowance/update", {}),
    ("GET", scan.CLOB, "/rewards/user/percentages", {}),
    ("GET", scan.CLOB, "/rewards/markets/current", {}),
    ("GET", scan.CLOB, "/book", {"token_id": "1", "extra": "x"}),
    ("GET", scan.CLOB, "/book", {"token_id": "../orders"}),
    ("GET", "https://evil.example", "/book", {"token_id": "1"}),
    ("GET", scan.GAMMA, "/markets", {"condition_ids": [COND_A], "limit": 500}),
])
def test_allow_list_refuses_before_any_socket(method, host, path, params):
    with pytest.raises(scan.ScanRefused):
        scan.check_public_get(method, host, path, params)
    public = reader(NoSocket())
    with pytest.raises(scan.ScanRefused):
        public.get(host, path, params) if method == "GET" else scan.check_public_get(method, host, path, params)
    assert public.used == 0


def test_scan_emits_per_outcome_reward_geometry_and_skips_ended_or_unrewarded():
    opener = Opener()
    pool = {"percentages": {COND_A: 12.5}}
    result = scan.run_scan(reader=reader(opener), events_config=events(), now_utc=NOW,
                           reader_rewards=lambda day: (pool, None))
    assert result["schema_version"] == "reward_scan_v1" and result["campaign"] == "owner-discretionary"
    assert result["markets_considered"] == 2 and result["outcome_count"] == 4
    # Unrewarded market B reads no book; the ended event is not read at all.
    assert sum("/book" in c for c in opener.calls) == 1 and not any("d" * 64 in c for c in opener.calls)
    rows = {(r["condition_id"], r["outcome"]): r for r in result["outcomes"]}
    yes = rows[(COND_A, "Yes")]
    assert (yes["daily_reward_rate"], yes["max_spread_cents"], yes["min_size"]) == (10.0, 4.5, 50.0)
    # Size-cutoff mid: best bid >= 50 is 0.40, best ask >= 50 is 0.44 -> 0.42; raw spread 0.04.
    assert (yes["mid"], yes["spread"], yes["mid_in_reward_band"]) == (0.42, 0.04, True)
    assert yes["one_sided_score_factor"] == pytest.approx(1 / 3, abs=1e-6)
    # Inside 4.5c: bids 0.40 (100) and 0.39 (20 < min size, excluded); asks 0.44 (80) only.
    assert (yes["resting_bid_size_in_band"], yes["resting_ask_size_in_band"]) == (100, 80)
    assert (yes["tightest_eligible_bid"], yes["tightest_eligible_distance_cents"], yes["cash_needed_pusd"]) == (0.42, 0.0, 21.0)
    no = rows[(COND_A, "No")]
    assert (no["mid"], no["best_bid"], no["best_ask"]) == (0.58, 0.56, 0.6)
    assert (no["resting_bid_size_in_band"], no["resting_ask_size_in_band"]) == (80, 100)
    assert (no["tightest_eligible_bid"], no["cash_needed_pusd"]) == (0.58, 29.0)
    assert yes["our_pool_percentage"] == 12.5 and rows[(COND_B, "Yes")]["our_pool_percentage"] is None
    assert rows[(COND_B, "No")]["status"] == "no_active_reward" and rows[(COND_B, "No")]["daily_reward_rate"] == 0.0
    assert result["status_counts"] == {"observed": 2, "no_active_reward": 2}
    assert result["public_gets"] == {"used": 3, "failed": 0, "max": 2000}


def test_mid_outside_reward_band_scores_zero_one_sided_and_explicit_condition_uses_gamma():
    result = scan.run_scan(reader=reader(), events_config={"locations": []}, conditions=[COND_X], now_utc=NOW)
    rows = {r["outcome"]: r for r in result["outcomes"]}
    assert set(rows) == {"Over", "Under"} and rows["Over"]["source"] == "explicit_condition"
    assert rows["Over"]["mid"] == 0.04 and rows["Over"]["mid_in_reward_band"] is False
    assert rows["Over"]["one_sided_score_factor"] == 0.0 and rows["Under"]["mid_in_reward_band"] is False
    assert result["pool_percentage_status"] == "reader_not_requested"


def test_budget_exhaustion_defers_rows_instead_of_dropping_them():
    result = scan.run_scan(reader=reader(max_gets=1), events_config=events(), now_utc=NOW)
    statuses = [r["status"] for r in result["outcomes"]]
    assert result["outcome_count"] == 4 and statuses.count("budget_deferred") == 4
    assert result["public_gets"]["used"] == 1


def test_book_identity_mismatch_is_refused():
    fixtures = dict(FIXTURES)
    fixtures[("/book", YES_A)] = book(COND_B, YES_A, [(0.4, 100)], [(0.44, 100)])
    result = scan.run_scan(reader=reader(Opener(fixtures)), events_config=events(), now_utc=NOW)
    row = next(r for r in result["outcomes"] if r["condition_id"] == COND_A)
    assert row["status"] == "book_unavailable" and row["errors"] == ["book:book_identity_refused"]


def test_one_sided_book_has_no_mid_and_no_cash_estimate():
    fixtures = dict(FIXTURES)
    fixtures[("/book", YES_A)] = book(COND_A, YES_A, [(0.4, 100)], [])
    result = scan.run_scan(reader=reader(Opener(fixtures)), events_config=events(), now_utc=NOW)
    row = next(r for r in result["outcomes"] if r["condition_id"] == COND_A)
    assert row["status"] == "two_sided_mid_unavailable" and row["mid"] is None and row["cash_needed_pusd"] is None


def test_pool_percentage_shapes_and_reader_failure_are_explicit():
    assert scan.pool_percentages({"percentages": {COND_A.upper().replace("0X", "0x"): "3"}}) == {COND_A: 3.0}
    assert scan.pool_percentages({"percentages": [{"condition_id": COND_A, "percentage": 4}]}) == {COND_A: 4.0}
    assert scan.pool_percentages({"percentages": "garbage"}) == {}
    result = scan.run_scan(reader=reader(), events_config=events(), now_utc=NOW,
                           reader_rewards=lambda day: (None, "reader_timeout"))
    assert result["pool_percentage_status"] == "reader_timeout" and result["outcome_count"] == 4


def test_reader_is_invoked_as_client_cli_child_process(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return subprocess.CompletedProcess(command, 1, stdout=json.dumps(
            {"error": "wallet_reader_client_failed", "reason": "http_503"}), stderr="")
    monkeypatch.setattr(scan.subprocess, "run", fake_run)
    assert scan.read_reader_rewards("2026-09-28") == (None, "reader_http_503")
    assert seen["command"][1:] == ["-m", "weather.market.wallet_reader_client", "rewards", "--date",
                                   "2026-09-28", "--timeout", "20"]
    monkeypatch.setattr(scan.subprocess, "run", lambda command, **kw: subprocess.CompletedProcess(
        command, 0, stdout=json.dumps({"date": "2026-09-28", "percentages": {COND_A: 1}}), stderr=""))
    payload, error = scan.read_reader_rewards("2026-09-28")
    assert error is None and scan.pool_percentages(payload) == {COND_A: 1.0}


def test_cli_writes_timestamped_and_latest_files(tmp_path, monkeypatch, capsys):
    config = tmp_path / "events.json"
    config.write_text(json.dumps(events(end="2099-01-01T00:00:00Z")), encoding="utf-8")
    public = reader()
    monkeypatch.setattr(scan, "PublicReader", lambda **kw: public)
    assert scan.main(["scan", "--out", str(tmp_path / "out"), "--events-config", str(config), "--no-reader"]) == 0
    files = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert len(files) == 2 and "latest.json" in files and files[1].startswith("reward_scan_")
    latest = json.loads((tmp_path / "out" / "latest.json").read_text(encoding="utf-8"))
    assert latest["pool_percentage_status"] == "reader_not_requested" and latest["outcome_count"] == 4
    assert json.loads(capsys.readouterr().out)["outcomes"] == 4


def test_cli_refuses_bad_arguments_before_network(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scan, "PublicReader", lambda **kw: pytest.fail("reader constructed"))
    assert scan.main(["scan", "--condition", "0x1234", "--out", str(tmp_path)]) == 2
    assert scan.main(["scan", "--max-gets", "0", "--out", str(tmp_path)]) == 2
