"""Guards: public GET-only batching, cap detection, pacing, event labels and HKO finality."""

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from weather.market.hko_settlement import HKODailyExtractAdapter, hko_value
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


def hko_payload(family, value="24.8", completeness="C"):
    return {"type": [f"Daily {'Maximum' if family == 'highest' else 'Minimum'} Temperature (°C) at the Hong Kong Observatory"],
            "fields": ["年/Year", "月/Month", "日/Day", "數值/Value", "數據完整性/data Completeness"],
            "data": [["2020", "1", "2", value, completeness]]}


def test_hko_reader_preserves_tenths_and_refuses_to_certify_revisions():
    day = date(2020, 1, 2)
    payloads = (hko_payload("highest"), hko_payload("lowest", "15.2"))
    adapter = HKODailyExtractAdapter(lambda target: payloads)
    result = adapter.evaluate(U["hong-kong"], day, as_of=NOW)
    assert result.maximum == Decimal("24.8")
    assert result.minimum == Decimal("15.2")
    assert result.status == "initial_publication_unverified"
    bins = [parse_bin_label(label, continuous=True) for label in ("23°C or below", "24°C", "25°C or higher")]
    assert all(p.possible for p in possible_bins(result, "highest", bins))
    final = adapter.evaluate(U["hong-kong"], day, as_of=NOW, initial_publication_verified=True)
    assert [p.interval.label for p in possible_bins(final, "highest", bins) if p.possible] == ["24°C"]
    assert hko_value(hko_payload("highest", completeness="N"), day, "highest") is None
    with pytest.raises(ValueError, match="series"):
        hko_value(payloads[0], day, "lowest")
    with pytest.raises(ValueError, match="precision"):
        hko_value(hko_payload("highest", "24.88"), day, "highest")
    assert WUDailyHistoryAdapter().evaluate(U["jinan"], day, as_of=NOW).status == "not_implemented"


def test_hko_missing_publication_waits_seven_days():
    day = date(2020, 1, 2)
    adapter = HKODailyExtractAdapter(lambda target: (hko_payload("highest", completeness="N"),
                                                    hko_payload("lowest", completeness="N")))
    before = datetime(2020, 1, 10, 4, 58, tzinfo=timezone.utc)
    after = datetime(2020, 1, 10, 4, 59, tzinfo=timezone.utc)
    assert adapter.evaluate(U["hong-kong"], day, as_of=before).status == "missing"
    assert adapter.evaluate(U["hong-kong"], day, as_of=after).status == "lowest_bracket_fallback"


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
