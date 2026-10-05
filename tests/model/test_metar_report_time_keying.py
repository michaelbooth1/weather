"""M0: METAR rows are keyed on AWC ``obsTime``, not the nominal ``reportTime``.

AWC stamps a routine METAR with the nominal hour, so the 23:5x local report of
day D-1 carries a ``reportTime`` on day D. ``metar-parser-v3`` keyed on that
field, which (a) carried D-1's last report into D as a "00:00" reading, (b)
dropped D's own 23:5x report, and (c) served D-1's reading as D's current
temperature until the first report of D. These tests drive the production
fetcher/parser (``fetch_metar`` -> ``parse_metar_payload``) and the production
floor (``guidance_physical_floor``) with AWC-shaped fixtures.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from weather.model.model_sources import SOURCE_PAYLOAD_CONTRACTS
from weather.model.source_adapters import fetch_source
from weather.model.toronto_model import TorontoHighTempModel


def _epoch(iso_utc):
    return int(datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).timestamp())


def awc_row(obs_utc, report_utc, temp_c, *, metar_type="METAR", raw=None, icao="KMIA", **extra):
    row = {
        "icaoId": icao,
        "receiptTime": obs_utc.replace("Z", ".000Z"),
        "obsTime": _epoch(obs_utc) if obs_utc else None,
        "reportTime": report_utc.replace("Z", ".000Z") if report_utc else None,
        "metarType": metar_type,
        "temp": temp_c,
        "dewp": 20.0,
        "wdir": 90,
        "wspd": 5,
        "rawOb": raw or f"{metar_type} {icao} {temp_c}",
    }
    row.update(extra)
    return row


def fetch(model, payload):
    model.get_json = lambda _url, _params: payload
    return model.fetch_metar()


def metar_sources(data):
    return {"metar": {"ok": True, "data": data}}


def test_parser_contract_is_bumped_to_v4_and_recorded_on_fetch():
    assert SOURCE_PAYLOAD_CONTRACTS["metar"] == ("metar-parser-v4", "metar-payload-v1")
    model = TorontoHighTempModel(target_date="2026-08-29", market_id="miami")
    model.get_json = lambda _url, _params: [
        awc_row("2026-08-29T13:53:00Z", "2026-08-29T14:00:00Z", 30.0)
    ]
    _, item = fetch_source(
        "metar",
        model.source_fetcher_with_contract("metar", model.fetch_metar),
        fetched_at="2026-08-29T14:01:00+00:00",
    )
    assert item["ok"] is True
    assert item["parser_version"] == "metar-parser-v4"
    assert item["payload_schema_version"] == "metar-payload-v1"


def test_kmia_defect_case_previous_day_last_report_no_longer_lifts_the_floor():
    """KMIA 2026-08-29 shape: D-1's warm 23:53 report must not set D's floor."""

    model = TorontoHighTempModel(target_date="2026-08-29", market_id="miami")
    payload = [
        # AWC returns newest first.
        awc_row("2026-08-30T03:53:00Z", "2026-08-30T04:00:00Z", 28.3),  # D 23:53 EDT
        awc_row("2026-08-29T18:53:00Z", "2026-08-29T19:00:00Z", 29.4),  # D 14:53 EDT
        awc_row("2026-08-29T04:53:00Z", "2026-08-29T05:00:00Z", 27.0),  # D 00:53 EDT
        awc_row("2026-08-29T03:53:00Z", "2026-08-29T04:00:00Z", 30.0),  # D-1 23:53 EDT
    ]

    data = fetch(model, payload)

    times = [row["time"] for row in data["rows"]]
    assert times == ["00:53", "14:53", "23:53"]
    assert all(row["row_time_basis"] == "obs_time" for row in data["rows"])
    # (a) the carried D-1 report (86.0 F) is gone from every derived field.
    assert data["same_day_max_native"] == pytest.approx(29.4 * 9 / 5 + 32)
    floor = model.guidance_physical_floor(sources=metar_sources(data))
    assert floor == pytest.approx(29.4 * 9 / 5 + 32)
    assert model.round_half_up(floor) == 85
    # (b) D's own 23:53 report stays in D and is the latest reading.
    assert data["latest"]["obs_time"] == "2026-08-30T03:53:00Z"
    assert data["latest"]["report_time"] == "2026-08-30T04:00:00.000Z"
    assert data["temp_native"] == pytest.approx(28.3 * 9 / 5 + 32)
    # Top-level report_time keeps provider semantics for trigger consumers.
    assert data["report_time"] == "2026-08-30T04:00:00.000Z"


def test_early_pass_before_first_report_of_day_serves_no_current_reading():
    """(c) At 00:10 local only D-1 reports exist; none may stand in for D."""

    model = TorontoHighTempModel(target_date="2026-09-19", market_id="nyc")
    payload = [
        awc_row("2026-09-19T03:51:00Z", "2026-09-19T04:00:00Z", 21.7, icao="KLGA"),  # D-1 23:51 EDT
        awc_row("2026-09-19T02:51:00Z", "2026-09-19T03:00:00Z", 22.2, icao="KLGA"),  # D-1 22:51 EDT
    ]

    data = fetch(model, payload)

    assert data["rows"] == []
    assert data["latest"] is None
    assert data["target_date_match"] is False
    assert data["temp_native"] is None
    assert data["same_day_max_native"] is None
    assert model.source_data(metar_sources(data), "metar") == {}


def test_routine_speci_and_cor_keep_their_semantics():
    model = TorontoHighTempModel(target_date="2026-08-29", market_id="miami")
    routine_original = awc_row(
        "2026-08-29T17:53:00Z", "2026-08-29T18:00:00Z", 30.6,
        raw="METAR KMIA 291753Z 09005KT 31/20",
    )
    routine_cor = awc_row(
        "2026-08-29T17:53:00Z", "2026-08-29T18:00:00Z", 31.1,
        raw="METAR KMIA 291753Z COR 09005KT 31/20",
    )
    speci = awc_row(
        "2026-08-29T18:12:00Z", "2026-08-29T18:12:00Z", 31.7,
        metar_type="SPECI", raw="SPECI KMIA 291812Z 09005KT 32/20",
    )
    routine_next = awc_row("2026-08-29T18:53:00Z", "2026-08-29T19:00:00Z", 30.0)

    data = fetch(model, [routine_next, speci, routine_cor, routine_original])

    rows = data["rows"]
    # Routine reports move from the nominal hour to the observation minute;
    # a SPECI's reportTime already equals its observation time.
    assert [row["time"] for row in rows] == ["13:53", "13:53", "14:12", "14:53"]
    assert rows[2]["raw"].startswith("SPECI")
    assert rows[2]["obs_time"] == "2026-08-29T18:12:00Z"
    # COR is not filtered (v3 semantics preserved): both versions of the
    # 13:53 report are kept and the running max sees the corrected value.
    assert {row["raw"] for row in rows[:2]} == {routine_original["rawOb"], routine_cor["rawOb"]}
    assert data["same_day_max_native"] == pytest.approx(31.7 * 9 / 5 + 32)
    assert data["latest"]["time"] == "14:53"


def test_exact_duplicates_are_kept_and_order_is_deterministic():
    model = TorontoHighTempModel(target_date="2026-08-29", market_id="miami")
    first = awc_row("2026-08-29T16:53:00Z", "2026-08-29T17:00:00Z", 30.0)
    second = dict(first)
    later = awc_row("2026-08-29T17:53:00Z", "2026-08-29T18:00:00Z", 29.0)

    forward = fetch(model, [first, second, later])
    backward = fetch(model, [later, second, first])

    assert len(forward["rows"]) == 3
    assert forward["rows"] == backward["rows"]
    assert forward["latest"]["time"] == "13:53"
    assert forward["same_day_max_native"] == pytest.approx(86.0)


def test_missing_obs_time_falls_back_to_report_time_and_is_labelled():
    model = TorontoHighTempModel(target_date="2026-08-29", market_id="miami")
    row = awc_row("2026-08-29T16:53:00Z", "2026-08-29T17:00:00Z", 30.0)
    row["obsTime"] = None
    unusable = awc_row("2026-08-29T15:53:00Z", None, 35.0)
    unusable["obsTime"] = "not-a-time"

    data = fetch(model, [row, unusable])

    assert len(data["rows"]) == 1
    assert data["rows"][0]["row_time_basis"] == "report_time_fallback"
    assert data["rows"][0]["obs_time"] is None
    assert data["rows"][0]["time"] == "13:00"


def test_obs_time_accepts_iso_text_and_rejects_naive_values():
    model = TorontoHighTempModel(target_date="2026-08-29", market_id="miami")
    assert model.metar_obs_time_utc("2026-08-29T16:53:00Z") == datetime(2026, 8, 29, 16, 53, tzinfo=timezone.utc)
    assert model.metar_obs_time_utc(str(_epoch("2026-08-29T16:53:00Z"))) == datetime(
        2026, 8, 29, 16, 53, tzinfo=timezone.utc
    )
    assert model.metar_obs_time_utc("2026-08-29T16:53:00") is None
    assert model.metar_obs_time_utc(True) is None
    assert model.metar_obs_time_utc("") is None


def test_fall_back_dst_day_keys_on_local_obs_date_and_orders_by_instant():
    """2026-11-01 America/New_York has 25 local hours and a repeated 01:xx."""

    model = TorontoHighTempModel(target_date="2026-11-01", market_id="nyc")
    payload = [
        awc_row("2026-11-02T04:51:00Z", "2026-11-02T05:00:00Z", 10.0, icao="KLGA"),  # D 23:51 EST
        awc_row("2026-11-01T06:51:00Z", "2026-11-01T07:00:00Z", 12.0, icao="KLGA"),  # D 01:51 EST
        awc_row("2026-11-01T06:15:00Z", "2026-11-01T06:15:00Z", 12.5, icao="KLGA",
                metar_type="SPECI"),  # D 01:15 EST
        awc_row("2026-11-01T05:51:00Z", "2026-11-01T06:00:00Z", 13.0, icao="KLGA"),  # D 01:51 EDT
        awc_row("2026-11-01T04:51:00Z", "2026-11-01T05:00:00Z", 14.0, icao="KLGA"),  # D 00:51 EDT
        awc_row("2026-11-01T03:51:00Z", "2026-11-01T04:00:00Z", 20.0, icao="KLGA"),  # D-1 23:51 EDT
    ]

    data = fetch(model, payload)

    obs = [row["obs_time"] for row in data["rows"]]
    assert obs == [
        "2026-11-01T04:51:00Z",
        "2026-11-01T05:51:00Z",
        "2026-11-01T06:15:00Z",
        "2026-11-01T06:51:00Z",
        "2026-11-02T04:51:00Z",
    ]
    assert [row["time"] for row in data["rows"]] == ["00:51", "01:51", "01:15", "01:51", "23:51"]
    assert data["latest"]["time"] == "23:51"
    assert data["same_day_max_native"] == pytest.approx(14.0 * 9 / 5 + 32)


def test_spring_forward_day_keeps_last_report_in_its_own_day():
    model = TorontoHighTempModel(target_date="2026-03-08", market_id="chicago")
    payload = [
        awc_row("2026-03-09T04:51:00Z", "2026-03-09T05:00:00Z", 5.0, icao="KORD"),  # D 23:51 CDT
        awc_row("2026-03-08T08:51:00Z", "2026-03-08T09:00:00Z", 2.0, icao="KORD"),  # D 03:51 CDT
        awc_row("2026-03-08T05:51:00Z", "2026-03-08T06:00:00Z", 15.0, icao="KORD"),  # D-1 23:51 CST
    ]

    data = fetch(model, payload)

    assert [row["time"] for row in data["rows"]] == ["03:51", "23:51"]
    assert data["same_day_max_native"] == pytest.approx(41.0)


def test_celsius_market_keys_on_observation_date():
    model = TorontoHighTempModel(target_date="2026-06-24", market_id="toronto")
    payload = [
        awc_row("2026-06-25T03:58:00Z", "2026-06-25T04:00:00Z", 19.0, icao="CYYZ"),  # D 23:58 EDT
        awc_row("2026-06-24T18:00:00Z", "2026-06-24T18:00:00Z", 27.0, icao="CYYZ"),  # D 14:00 EDT
        awc_row("2026-06-24T03:58:00Z", "2026-06-24T04:00:00Z", 29.0, icao="CYYZ"),  # D-1 23:58 EDT
    ]

    data = fetch(model, payload)

    assert [row["time"] for row in data["rows"]] == ["14:00", "23:58"]
    assert data["same_day_max_native"] == pytest.approx(27.0)
    assert data["temp_native"] == pytest.approx(19.0)


def test_cutoff_alignment_never_admits_a_report_earlier_than_v3_did():
    """Point-in-time: a routine report observed at 13:53 is not visible at the
    13:00 cutoff under either keying; obsTime keying only moves it to the
    minute WU history prints it, which is the training key."""

    model = TorontoHighTempModel(target_date="2026-08-29", market_id="miami")
    data = fetch(model, [awc_row("2026-08-29T17:53:00Z", "2026-08-29T18:00:00Z", 30.0)])
    rows = model.station_feature_rows("metar", data)

    assert model.source_rows_until_cutoff(rows, 13) == []
    assert [row["time"] for row in model.source_rows_until_cutoff(rows, 14)] == ["13:53"]


def test_snapshot_writer_records_v4_and_retained_raw_reparses_to_the_same_rows(tmp_path):
    """Production writer: the observation sidecar binds parser v4 and keeps the
    raw AWC payload (with ``obsTime``), so a replay can re-derive v4 rows from
    the retained bytes; stored v3 rows are never rewritten."""

    from weather.collection.snapshot_store import SnapshotStore

    model = TorontoHighTempModel(target_date="2026-08-29", market_id="miami")
    payload = [
        awc_row("2026-08-30T03:53:00Z", "2026-08-30T04:00:00Z", 28.3),
        awc_row("2026-08-29T03:53:00Z", "2026-08-29T04:00:00Z", 30.0),
    ]
    model.get_json = lambda _url, _params: payload
    _, item = fetch_source(
        "metar",
        model.source_fetcher_with_contract("metar", model.fetch_metar),
        fetched_at="2026-08-30T03:58:00+00:00",
    )
    data = item["data"]
    sources = {"metar": item}

    store = SnapshotStore(root=tmp_path, event_slug="event")
    observation = store.write_observation_payloads(
        sources,
        "s1",
        datetime(2026, 8, 30, 3, 58, tzinfo=timezone.utc),
        "model-v",
    )[0]

    assert observation["parser_version"] == "metar-parser-v4"
    retained = json.loads(Path(observation["raw_payload_path"]).read_text(encoding="utf-8"))
    assert [row["obsTime"] for row in retained] == [row["obsTime"] for row in payload]
    replay_model = TorontoHighTempModel(target_date="2026-08-29", market_id="miami")
    assert replay_model.parse_metar_payload(retained) == data["rows"]
    assert [row["time"] for row in data["rows"]] == ["23:53"]
