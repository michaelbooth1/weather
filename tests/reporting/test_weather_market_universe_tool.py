"""Offline contracts for the bounded 95d research inventory."""
import hashlib
import importlib.util
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("weather_market_universe", Path(__file__).resolve().parents[2] / "tools" / "weather_market_universe.py")
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def test_endpoint_allowlist_and_offline_cache(tmp_path):
    cache = w.PublicCache(tmp_path)
    for base, path in [(w.CLOB, "/orders"), (w.CLOB, "/auth/api-key"), ("https://example.com", "/events")]:
        with pytest.raises(ValueError):
            cache.get(base, path)
    with pytest.raises(ValueError):
        cache.get(w.FORECAST, "/v1/forecast", apikey="forbidden")
    with pytest.raises(FileNotFoundError):
        cache.get(w.GAMMA, "/events/keyset")


def test_closed_scope_uses_actual_closure_not_end_date():
    cutoff = w.dt("2026-07-26T20:20:00Z")
    assert w.in_scope({"closed": True, "closedTime": "2026-08-01T00:00:00Z", "endDate": "2025-01-01"}, cutoff)
    assert not w.in_scope({"closed": True, "endDate": "2026-08-01"}, cutoff)
    assert not w.in_scope({"closed": True, "closedTime": "2026-07-01T00:00:00Z"}, cutoff)


def test_datetime_preserves_offset():
    assert w.dt("2026-09-24T16:20:00-04:00") == w.dt("2026-09-24T20:20:00Z")


def test_family_alias_and_month_not_misread_as_day():
    assert w.family({"title": "Highest temperature in Seoul (Incheon) on September 25?"}) == "highest temperature | Seoul"
    assert w.family({"title": "September 2026 Temperature Increase (C)"}) == "<month> 2026 Temperature Increase (C)"
    assert w.family({"title": "Where will it rain on September 25?"}) == "Where will it rain on <date>?"


def test_sport_exclusion_and_named_storm_retention():
    assert not w.weather_event({"title": "Panthers vs. Hurricanes", "tags": [{"id": "84"}]})
    assert not w.weather_event({"title": "Will Snowflake (SNOW) beat quarterly earnings?"})
    assert w.weather_event({"title": "How strong will Nolo be?", "tags": [{"id": "84"}]})
    assert w.weather_event({"title": "Rain during the Azerbaijan Grand Prix?"})


def test_stale_open_daily_events_are_not_opportunities():
    e = {"title": "Highest temperature in Jinan on May 20?", "slug": "highest-temperature-in-jinan-on-may-20-2026", "active": True, "closed": False, "markets": [{"acceptingOrders": True}]}
    assert not w.viable_event(e, "2026-09-24T20:20:00Z", {"Jinan": {"timezone": "Asia/Shanghai"}})
    e["slug"] = "highest-temperature-in-jinan-on-september-24-2026"
    assert not w.viable_event(e, "2026-09-24T20:20:00Z", {"Jinan": {"timezone": "Asia/Shanghai"}})
    e["slug"] = "highest-temperature-in-jinan-on-september-25-2026"
    assert w.viable_event(e, "2026-09-24T20:20:00Z", {"Jinan": {"timezone": "Asia/Shanghai"}})


def test_books_are_sorted_and_one_sided_is_unknown():
    reply = {"status": 200, "retrieved_at": "x", "body": {"bids": [{"price": ".1", "size": "100"}, {"price": ".48", "size": "20"}], "asks": [{"price": ".9", "size": "200"}, {"price": ".52", "size": "30"}]}}
    b = w.book_metrics(reply, 4.5)
    assert b["best_bid"] == .48 and b["best_ask"] == .52
    assert b["bid_shares_within_reward_distance"] == 20
    assert b["ask_shares_within_reward_distance"] == 30
    reply["body"]["asks"] = []
    assert w.book_metrics(reply, 4.5)["spread"] is None


def test_source_fallback_and_minimum_are_not_same_shape():
    assert w.source_kind({"description": "NOAA timeseries, Weather Underground fallback"}) == "NOAA timeseries; WU fallback"
    assert w.bucket("highest temperature | Paris", [1], "NOAA timeseries; WU fallback", 200)[0] == "Ingest later"
    assert w.bucket("lowest temperature | Jinan", [1], "WU Daily Observations", 200)[0] == "Ingest later"
    assert w.bucket("highest temperature | Jinan", [1], "WU Daily Observations", 0)[0] != "Ingest now"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def test_fetch_evidence_assembles_tracked_and_pinned_files_and_checks_hashes(tmp_path):
    repo = tmp_path / "repo"
    inventory = repo / w.INVENTORY_PATH_IN_COMMIT
    inventory.mkdir(parents=True)
    files = {"markets.csv": b"market_id\n1\n", "summary.json": b"{}\n"}
    for name, data in files.items():
        (inventory / name).write_bytes(data)
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "evidence")
    commit = _git(repo, "rev-parse", "HEAD")
    tracked = tmp_path / "tracked"
    tracked.mkdir()
    (tracked / "summary.json").write_bytes(files["summary.json"])
    sums = "".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n, d in sorted(files.items()))
    (tracked / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")

    out = tmp_path / "out"
    w.fetch_evidence(out, tracked=tracked, commit=commit, repo=repo)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == files

    (tracked / "summary.json").write_bytes(b"tampered")
    with pytest.raises(SystemExit, match="does not match"):
        w.fetch_evidence(tmp_path / "out2", tracked=tracked, commit=commit, repo=repo)
    with pytest.raises(SystemExit, match="git fetch origin"):
        w.fetch_evidence(tmp_path / "out3", tracked=tracked, commit="0" * 40, repo=repo)
