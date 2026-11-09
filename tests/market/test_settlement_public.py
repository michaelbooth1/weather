"""Guards: public GET-only batching, cap detection, pacing, event labels and HKO finality."""

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError

import pytest

from weather.market.hko_settlement import HKODailyExtractAdapter, parse_daily_extract
from weather.market.metar_settlement import WUDailyHistoryAdapter, main, possible_bins
from weather.market.settlement_public import PublicSettlementClient, public_json_or_text
from weather.market.weather_universe import load_weather_universe, parse_bin_label

U = load_weather_universe()
NOW = datetime(2026, 9, 28, 20, tzinfo=timezone.utc)


def client_for(get):
    instant = [0.0]
    calls = []

    def sleep(delay):
        instant[0] += delay

    def counted_get(url):
        calls.append((instant[0], url))
        return get(url)

    return PublicSettlementClient(counted_get, clock=lambda: instant[0], sleep=sleep), calls


def test_multistation_batching_and_one_second_limit():
    def get(url):
        query = parse_qs(urlparse(url).query)
        assert query["hours"] == ["30"]
        assert "." not in query["date"][0]
        return "\n".join(f"METAR {station} 281800Z 18/10" for station in query["ids"][0].split(","))
    client, calls = client_for(get)
    stations = ["KLGA", "KATL", "KORD", "KSEA", "KSFO", "KLAX", "CYYZ"]
    records, stats = client.metars(stations, NOW.replace(microsecond=123456))
    assert {r.station for r in records} == set(stations)
    assert stats["request_count"] == 2
    assert calls[1][0] - calls[0][0] >= 1
    assert not stats["errors"]


def test_saturated_response_splits_and_discards_truncated_parent():
    def get(url):
        ids = parse_qs(urlparse(url).query)["ids"][0].split(",")
        if len(ids) > 1:
            return "\n".join(["METAR KLGA 281800Z 99/10"] * 400)
        return f"METAR {ids[0]} 281800Z 18/10"
    client, calls = client_for(get)
    records, stats = client.metars(["KLGA", "KATL"], NOW)
    assert len(records) == 2
    assert all(r.temperature_c == 18 for r in records)
    assert stats["request_count"] == 3
    assert [instant for instant, url in calls] == [0, 1, 2]


def test_single_station_saturation_splits_time_and_fails_closed_if_persistent():
    client, calls = client_for(lambda url: "\n".join(["METAR KLGA 281800Z 99/10"] * 400))
    records, stats = client.metars(["KLGA"], NOW)
    assert not records
    assert "saturated" in stats["errors"][0]
    assert len(calls) < 10


def test_http_failure_stops_awc_requests():
    def get(url):
        raise OSError("HTTP 429")
    client, calls = client_for(get)
    records, stats = client.metars([s.station_id for s in U.values() if s.settlement_kind == "metar_routine"], NOW)
    assert not records
    assert len(calls) == 1
    assert stats["errors"] == ["HTTP 429"]


@pytest.mark.parametrize("url", [
    "http://aviationweather.gov/api/data/metar", "https://gamma-api.polymarket.com/markets",
    "https://clob.polymarket.com/order", "https://user:password@aviationweather.gov/api/data/metar",
])
def test_nonpublic_or_order_urls_refused_before_network(url):
    with pytest.raises(ValueError, match="allowlist"):
        public_json_or_text(url)


def test_event_bins_exact_slug_and_labels_only():
    slug = "highest-temperature-in-toronto-on-september-28-2026"
    client, calls = client_for(lambda url: json.dumps([dict(slug=slug, markets=[
        dict(groupItemTitle="14°C", outcomePrices="not a number; must never be parsed")])]))
    assert client.event_bins(slug) == ["14°C"]
    assert client.event_bins("other") == []


def hko_payload(day="02", high="24.8", low="15.2", month=1):
    return json.dumps({"stn": {"data": [{"month": month, "dayData": [
        [day, "1020.0", high, "20.0", low, "12.0", "70", "50", "0.0"]]}]}})


def test_hko_reader_preserves_tenths_and_refuses_to_certify_revisions():
    day = date(2020, 1, 2)
    snapshot = parse_daily_extract(hko_payload(), 2020, 1)
    adapter = HKODailyExtractAdapter(lambda target: snapshot)
    result = adapter.evaluate(U["hong-kong"], day, as_of=NOW)
    assert result.maximum == Decimal("24.8")
    assert result.minimum == Decimal("15.2")
    assert result.status == "initial_publication_unverified"
    bins = [parse_bin_label(label, continuous=True) for label in ("23°C or below", "24°C", "25°C or higher")]
    assert all(p.possible for p in possible_bins(result, "highest", bins))
    final = adapter.evaluate(U["hong-kong"], day, as_of=NOW, initial_publication_verified=True)
    assert [p.interval.label for p in possible_bins(final, "highest", bins) if p.possible] == ["24°C"]
    with pytest.raises(ValueError, match="month"):
        parse_daily_extract(hko_payload(month=2), 2020, 1)
    with pytest.raises(ValueError, match="precision"):
        parse_daily_extract(hko_payload(high="24.88"), 2020, 1)
    assert WUDailyHistoryAdapter().evaluate(U["jinan"], day, as_of=NOW).status == "not_implemented"


def test_hko_missing_publication_waits_seven_days():
    day = date(2020, 1, 2)
    snapshot = parse_daily_extract(hko_payload(high="***", low="***"), 2020, 1)
    adapter = HKODailyExtractAdapter(lambda target: snapshot)
    before = datetime(2020, 1, 10, 4, 58, tzinfo=timezone.utc)
    after = datetime(2020, 1, 10, 4, 59, tzinfo=timezone.utc)
    assert adapter.evaluate(U["hong-kong"], day, as_of=before).status == "source_unavailable"
    assert adapter.evaluate(U["hong-kong"], day, as_of=after).status == "lowest_bracket_fallback"


def test_review_m2_uncovered_date_never_collapses_to_the_lowest_bin():
    day = date(2026, 10, 20)
    snapshot = parse_daily_extract(hko_payload(day="15", month=10), 2026, 10)
    result = HKODailyExtractAdapter(lambda target: snapshot).evaluate(
        U["hong-kong"], day, as_of=datetime(2026, 11, 9, 12, tzinfo=timezone.utc))
    assert result.status == "source_unavailable"
    bins = [parse_bin_label(label, continuous=True) for label in ("23°C or below", "24°C", "25°C or higher")]
    assert all(p.possible for p in possible_bins(result, "highest", bins))
    # A lagged climate-series payload is not the named source at all.
    climate = ({"data": [["2026", "9", "30", "34.2", "C"]]}, {})
    result = HKODailyExtractAdapter(lambda target: climate).evaluate(U["hong-kong"], day, as_of=NOW)
    assert result.status == "source_unavailable"


def test_named_daily_extract_endpoint_and_official_development_fixture():
    from weather.paths import repo_path
    raw = repo_path("tests", "fixtures", "weather_expansion", "hko_daily_extract_202001.xml").read_text(encoding="utf-8")
    client, calls = client_for(lambda url: raw)
    snapshot = client.hko_payloads(date(2020, 1, 2))
    assert calls[0][1] == "https://www.weather.gov.hk/cis/dailyExtract/dailyExtract_202001.xml"
    assert snapshot.days[2] == (Decimal("20.4"), Decimal("17.4"))
    assert snapshot.covered_through == 31


def test_an_unpublished_daily_extract_file_is_unavailable():
    def get(url):
        raise HTTPError(url, 404, "Not Found", {}, None)
    client, calls = client_for(get)
    result = HKODailyExtractAdapter(client.hko_payloads).evaluate(
        U["hong-kong"], date(2026, 10, 20), as_of=NOW)
    assert result.status == "source_unavailable"


def test_cli_offline_current_event_and_missing_family(monkeypatch, capsys):
    def get(url):
        if "aviationweather.gov" in url:
            # No observations is a valid, explicit missing-data diagnostic.
            return ""
        slug = parse_qs(urlparse(url).query)["slug"][0]
        return json.dumps([dict(slug=slug, markets=[dict(groupItemTitle="20°C or below"),
                                                   dict(groupItemTitle="21°C or higher")])])
    client, calls = client_for(get)
    monkeypatch.setattr("weather.market.settlement_public.PublicSettlementClient", lambda: client)
    assert main(["now", "--family", "highest", "--cities", "toronto"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "missing"
    assert len(out["possible_bins"]) == 2
    assert out["event_slug"].startswith("highest-temperature-in-toronto-on-")
    assert main(["now", "--family", "lowest", "--cities", "singapore"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "family_unavailable"


def test_51_gamma_gets_and_hko_gets_are_paced_per_host():
    def get(url):
        if "weather.gov.hk" in url:
            return hko_payload()
        slug = parse_qs(urlparse(url).query)["slug"][0]
        return json.dumps([dict(slug=slug, markets=[dict(groupItemTitle="14°C")])])
    client, calls = client_for(get)
    for city in range(51):
        assert client.event_bins(f"event-{city}") == ["14°C"]
    for _ in range(3):
        client.hko_payloads(date(2020, 1, 2))
    by_host = {}
    for instant, url in calls:
        by_host.setdefault(urlparse(url).hostname, []).append(instant)
    assert len(by_host["gamma-api.polymarket.com"]) == 51
    for instants in by_host.values():
        assert all(b - a >= 1 for a, b in zip(instants, instants[1:]))


@pytest.mark.parametrize("host", ["gamma-api.polymarket.com", "www.weather.gov.hk"])
def test_three_consecutive_429s_disable_the_host(host):
    def get(url):
        raise HTTPError(url, 429, "Too Many Requests", {}, None)
    client, calls = client_for(get)
    for _ in range(3):
        with pytest.raises(HTTPError):
            if host == "gamma-api.polymarket.com":
                client.event_bins("event")
            else:
                client.hko_payloads(date(2020, 1, 2))
    with pytest.raises(OSError, match="stopped.*3 consecutive"):
        if host == "gamma-api.polymarket.com":
            client.event_bins("next-event")
        else:
            client.hko_payloads(date(2020, 1, 2))
    assert len(calls) == 3
    assert [instant for instant, url in calls] == [0, 1, 2]


def test_a_success_resets_the_consecutive_429_counter():
    responses = [429, 429, 200, 429, 429, 429]
    def get(url):
        if responses.pop(0) == 429:
            raise HTTPError(url, 429, "Too Many Requests", {}, None)
        return "[]"
    client, calls = client_for(get)
    for n in range(6):
        if n == 2:
            assert client.event_bins("event") == []
        else:
            with pytest.raises(HTTPError):
                client.event_bins("event")
    with pytest.raises(OSError, match="stopped"):
        client.event_bins("event")
    assert len(calls) == 6


def test_awc_snapshot_conflicting_revisions_are_not_resolved_by_row_order():
    client, calls = client_for(lambda url: "METAR CYYZ 281800Z 18/10\nMETAR CYYZ 281800Z COR 15/10")
    reports, diagnostics = client.metars(["CYYZ"], NOW)
    assert diagnostics["parse_flags"]["ambiguous_source_revision"] == 1
    assert all(r.temperature_c is None for r in reports)
    from weather.market.metar_settlement import MetarSettlementAdapter
    result = MetarSettlementAdapter().evaluate(U["toronto"], date(2026, 9, 28), reports, as_of=NOW)
    assert result.status == "source_unavailable"
