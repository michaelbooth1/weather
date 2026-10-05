"""Item 4: the observation trigger writes the METAR/SPECI ledger from its own fetch."""

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import weather.operations.observation_trigger as observation_trigger
from weather.sources import metar_reports

RAW = [
    {
        "icaoId": "KORD",
        "obsTime": 1782388260,
        "reportTime": "2026-06-25T12:00:00.000Z",
        "metarType": "METAR",
        "temp": 21.7,
        "rawOb": "METAR KORD 251151Z 27010KT 10SM 22/14 A3012 RMK AO2 T02170139",
    },
    {
        "icaoId": "KORD",
        "obsTime": 1782389400,
        "reportTime": "2026-06-25T12:10:00.000Z",
        "metarType": "SPECI",
        "temp": 21.1,
        "rawOb": "SPECI KORD 251210Z 28012G20KT 3SM TSRA 21/15 A3013 RMK AO2 T02110150",
    },
]


def fetch_state(tmp_path, now, sources):
    class Model:
        market_id = "chicago"
        target_date = date(2026, 6, 25)
        spec = SimpleNamespace(tz=timezone.utc, unit="F", icao="KORD")

        def __init__(self, **_kwargs):
            pass

        def load_last_good_sources(self):
            return {}

    config = SimpleNamespace(target_date=date(2026, 6, 25), event_slug="highest-temperature-in-chicago")
    with patch.object(observation_trigger, "spec_for_id", return_value=Model.spec), \
            patch.object(observation_trigger, "config_for_date", return_value=config), \
            patch.object(observation_trigger, "TorontoHighTempModel", Model), \
            patch.object(observation_trigger, "fetch_observation_sources", return_value=sources), \
            patch.object(observation_trigger, "observation_state_from_sources", return_value={"values": {}}):
        return observation_trigger.fetch_market_observation_state(
            "chicago",
            now=now,
            source_cache_root=tmp_path / "observation_source_cache",
        )


def test_trigger_captures_metar_and_speci_beside_attempt_cache_root(tmp_path, monkeypatch):
    monkeypatch.setattr(metar_reports, "_LAST_CAPTURE_AT", {})
    now = datetime(2026, 6, 25, 12, 14, tzinfo=timezone.utc)
    sources = {"metar": {"ok": True, "stale": False, "data": {"raw_payload": RAW}}}

    state = fetch_state(tmp_path, now, sources)

    assert state["metar_report_capture"]["status"] == "captured"
    assert state["metar_report_capture"]["appended"] == 2
    ledger = tmp_path / "metar_reports" / "chicago" / "metar_reports-2026-06-25.jsonl"
    records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert [record["report_type"] for record in records] == ["METAR", "SPECI"]
    assert [record["tgroup_temp_celsius"] for record in records] == [21.7, 21.1]

    again = fetch_state(tmp_path, now + timedelta(seconds=60), sources)
    assert again["metar_report_capture"]["status"] == "not_due"
    later = fetch_state(tmp_path, now + timedelta(seconds=120), sources)
    assert later["metar_report_capture"] == {"interval_seconds": 120.0, "appended": 0, "status": "captured"}


def test_trigger_skips_stale_metar_and_markets_without_metar(tmp_path, monkeypatch):
    monkeypatch.setattr(metar_reports, "_LAST_CAPTURE_AT", {})
    now = datetime(2026, 6, 25, 12, 14, tzinfo=timezone.utc)
    stale = {"metar": {"ok": True, "stale": True, "data": {"raw_payload": RAW}}}

    assert fetch_state(tmp_path, now, stale)["metar_report_capture"]["status"] == "skipped_not_fresh"
    assert fetch_state(tmp_path, now, {})["metar_report_capture"]["status"] == "not_configured"
    assert not (tmp_path / "metar_reports").exists()
