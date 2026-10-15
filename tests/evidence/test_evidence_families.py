"""S4 evidence families (OB-1, OB-2, OB-3, FC-1, FC-4, VR-3) on fixture payloads; no live endpoint.

Guards: docs/operations/EVIDENCE_HOST.md (DLv2 plan S4 verify row "first-seen rows for all 51
stations"; OB-1 METAR remark parsing and AWC row-cap rows; OB-3 SWOB fetches only new file names;
FC-1 hard daily meter and 429 cap; FC-4 KMZ to CAS with IssueTime run identity; VR-3 change-only
event rows, WARN-first source gate and the fetch-side embargo guard on the closed sweep).
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from maker_core.shadow.admission import EMBARGO_WINDOWS, FULL
from weather.evidence.child import ChildRunner, PollContext, load_family_channels
from weather.evidence.config import load_config, load_locations
from weather.evidence.fetch import Fetcher, Response
from weather.evidence.journal import EvidenceJournal, iter_segment_rows, read_raw, segment_dirs
from weather.evidence.families import fc1_openmeteo_meta, fc4_mosmix, ob1_metar, ob2_nws, ob3_native, vr3_gamma
from weather.evidence.reader import read
from weather.evidence.telemetry import FamilyTelemetry

LOCATIONS = load_locations()
CONFIG, CONFIG_SHA = load_config()
DAY = date(2026, 1, 2)
FULL_START = next(date.fromisoformat(s) for s, _, scope, _ in EMBARGO_WINDOWS if scope == FULL)


class Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


def _ctx(root, family, transport, clock, channel="ch", budget=10_000):
    journal = EvidenceJournal(root, family, clock=clock).open()
    telemetry = FamilyTelemetry(root, family, clock=clock)
    fetcher = Fetcher(user_agent="test", request_budget_per_hour=budget, telemetry=telemetry, transport=transport,
                      clock=lambda: 0.0)
    return PollContext(family, CONFIG["families"].get(family, {}), CONFIG["host"], journal, fetcher, telemetry,
                       LOCATIONS, clock, lambda _s: None, channel=channel)


def _events(root, family, day=DAY.isoformat()):
    out = []
    for segment in segment_dirs(root / family / day):
        out += [row for name, row in iter_segment_rows(segment) if name == "events.jsonl"]
    return out


def _rows(root, family, day=DAY.isoformat()):
    return read(family, "2030-01-01T00:00:00Z", "capture_check", days=[day], root=root).rows


# --------------------------------------------------------------------------------------------- OB-1
def test_metar_remarks_parse_t_group_extremes_slp_and_cor():
    parsed = ob1_metar.parse_remarks(
        "METAR KLGA 021251Z COR 31012KT 10SM FEW250 M01/M08 A3012 RMK AO2 SLP199 T10111078 10022 21011 401001017")
    assert parsed["cor"] is True and parsed["slp_hpa"] == pytest.approx(1019.9)
    assert (parsed["t_group_c"], parsed["t_group_dewpoint_c"]) == (-1.1, -7.8)
    assert (parsed["max6h_c"], parsed["min6h_c"]) == (2.2, -1.1)
    assert (parsed["max24h_c"], parsed["min24h_c"]) == (10.0, -1.7)
    plain = ob1_metar.parse_remarks("METAR EGLC 021250Z AUTO 24008KT 9999 NCD 09/05 Q1012")
    assert plain["t_group_c"] is None and plain["cor"] is False and plain["slp_group"] is False


def _metar_transport(calls, *, revision):
    def transport(url, headers, timeout, max_bytes):
        calls.append(url)
        ids = parse_qs(urlparse(url).query)["ids"][0].split(",")
        rows = [{"icaoId": i, "obsTime": 1767355800 + 3600 * revision, "receiptTime": "2026-01-02 12:13:00",
                 "rawOb": f"METAR {i} 02{12 + revision}50Z 00000KT 9999 FEW020 12/08 Q1015 RMK T01230081",
                 "metarType": "METAR", "temp": 12.3} for i in ids]
        return Response(url, 200, json.dumps(rows).encode())
    return transport


def test_first_seen_rows_for_all_51_stations_and_exactness_after_a_continuous_poll(tmp_path):
    config = json.loads(json.dumps(CONFIG))
    config["families"]["ob1_metar"]["channels"]["metar_sweep"]["enabled"] = False
    clock, mono, calls, revision = Clock(datetime(2026, 1, 2, 12, 15, tzinfo=timezone.utc)), [0.0], [], [0]

    def transport(url, headers, timeout, max_bytes):
        return _metar_transport(calls, revision=revision[0])(url, headers, timeout, max_bytes)

    def sleep(seconds):
        mono[0] += 61.0
        clock.value += timedelta(seconds=61)
        if len(calls) == 2:
            revision[0] = 1

    runner = ChildRunner("ob1_metar", config=config, config_sha256=CONFIG_SHA, root=tmp_path, repo_root=tmp_path,
                         locations=LOCATIONS, transport=transport, clock=clock,
                         local_clock=lambda: datetime(2026, 1, 2, 3, 0), sleep=sleep,
                         available_memory=lambda: 64 * 1024**3, disk_free=lambda: 500 * 1024**3,
                         monotonic=lambda: mono[0])
    runner.run(max_iterations=3)
    assert len(calls) == 3
    rows = _rows(tmp_path, "ob1_metar")
    stations = {r["body"]["station"] for r in rows}
    assert len(stations) == 51 and "VHHH" in stations and "HKO" not in stations
    assert {r["body"]["location"] for r in rows} == {loc["id"] for loc in LOCATIONS}
    first = [r for r in rows if "|2026-01-02T12:10:00Z|" in r["key"]]
    later = [r for r in rows if "|2026-01-02T13:10:00Z|" in r["key"]]
    assert len(first) == len(later) == 51
    assert not any(r["first_seen_exact"] for r in first) and all(r["first_seen_exact"] for r in later)
    assert all(r["availability_basis"] == "live_receipt" and r["parser_version"] == "ob1-metar-1" for r in rows)


def test_awc_row_cap_writes_a_cap_row(tmp_path):
    clock = Clock(datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc))
    many = [{"icaoId": "KLGA", "obsTime": 1767355800 + i * 60, "rawOb": f"SPECI KLGA {i}"} for i in range(400)]
    ctx = _ctx(tmp_path, "ob1_metar", lambda u, h, t, m: Response(u, 200, json.dumps(many).encode()), clock)
    channels = {c.name: c for c in ob1_metar.build(CONFIG["families"]["ob1_metar"], LOCATIONS)}
    ctx.channel = "metar_recent"
    channels["metar_recent"].poll(ctx)
    ctx.journal.close()
    caps = [e for e in _events(tmp_path, "ob1_metar") if e["kind"] == "cap"]
    assert caps and caps[0]["reason"] == "awc_row_cap" and caps[0]["rows"] == 400
    assert all(r["body"]["type"] == "SPECI" for r in _rows(tmp_path, "ob1_metar"))


# --------------------------------------------------------------------------------------------- OB-2
def test_nws_observations_are_keyed_by_station_and_timestamp(tmp_path):
    payload = {"features": [{"properties": {"timestamp": "2026-01-02T12:05:00+00:00", "rawMessage": "",
                                            "temperature": {"value": 3.3, "unitCode": "wmoUnit:degC",
                                                            "qualityControl": "V"}}}]}
    items = ob2_nws.observation_items(payload, station="KLGA", location="nyc", exact=True)
    assert items[0]["key"] == "KLGA|2026-01-02T12:05:00+00:00"
    assert items[0]["body"]["temperature"] == {"value": 3.3, "unit": "wmoUnit:degC", "qc": "V"}
    stations = ob2_nws.build(CONFIG["families"]["ob2_nws"], LOCATIONS)
    assert len(stations) == 1
    us = [loc for loc in LOCATIONS if loc.get("country_code") == "US"]
    assert len(us) == 11


# --------------------------------------------------------------------------------------------- OB-3
def test_hko_and_jma_parsers():
    csv_text = ("﻿Date time,Automatic Weather Station,Maximum Air Temperature Since Midnight(degree Celsius),"
                "Minimum Air Temperature Since Midnight(degree Celsius)\n"
                "202601021200,HK Observatory,21.4,17.9\n202601021200,Chek Lap Kok,22.0,18.1\n")
    items = ob3_native.hko_maxmin_items(csv_text, {"HK Observatory"})
    assert [i["key"] for i in items] == ["HK Observatory|202601021200"]
    assert items[0]["envelope"]["provider_time"] == "2026-01-02T04:00:00Z"
    rhr = ob3_native.hko_rhrread_items({"temperature": {"recordTime": "2026-01-02T12:00:00+08:00", "data": [
        {"place": "Hong Kong Observatory", "value": 20, "unit": "C"}, {"place": "Sha Tin", "value": 21}]}},
        {"Hong Kong Observatory"})
    assert [i["body"]["value"] for i in rhr] == [20]
    assert ob3_native.jma_block_name(datetime(2026, 1, 2, 17, 40, tzinfo=timezone(timedelta(hours=9)))) == "20260102_15"
    jma = ob3_native.jma_items({"20260102174000": {"temp": [9.1, 0]}, "bad": {}}, "44166")
    assert jma[0]["key"] == "44166|20260102174000" and jma[0]["envelope"]["provider_time"] == "2026-01-02T08:40:00Z"


def test_swob_fetches_only_new_file_names_and_keeps_raw_xml(tmp_path):
    clock = Clock(datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc))
    names = ["2026-01-02-1100-cytz-AUTO-swob.xml", "2026-01-02-1200-cytz-AUTO-swob.xml"]
    xml = '<om><element name="air_temp" uom="C" value="-3.1"/><element name="date_tm" value="2026-01-02T12:00:00.000Z"/></om>'
    fetched = []

    def transport(url, headers, timeout, max_bytes):
        fetched.append(url)
        if url.endswith("/"):
            return Response(url, 200 if "/CYTZ/" in url else 404,
                            "".join(f'<a href="{n}">{n}</a>' for n in names).encode())
        return Response(url, 200, xml.encode())

    cfg = json.loads(json.dumps(CONFIG["families"]["ob3_native"]))
    cfg["channels"]["eccc_swob"]["stations"] = ["CYTZ", "CXXX"]
    poll = {c.name: c for c in ob3_native.build(cfg, LOCATIONS)}["eccc_swob"].poll
    ctx = _ctx(tmp_path, "ob3_native", transport, clock, channel="eccc_swob")
    poll(ctx)
    first = len(fetched)
    poll(ctx)
    ctx.journal.close()
    assert first == 2 + len(names) and len(fetched) == first + 2  # second poll: listings only
    rows = _rows(tmp_path, "ob3_native")
    assert len(rows) == 2 and rows[0]["body"]["elements"]["air_temp"]
    assert read_raw(tmp_path, rows[0]["raw_ref"]).startswith(b"<om>")
    warns = [e for e in _events(tmp_path, "ob3_native") if e["kind"] == "warn"]
    assert [w["station"] for w in warns] == ["CXXX"]


# --------------------------------------------------------------------------------------------- FC-1
def test_open_meteo_meta_rows_meter_and_429(tmp_path):
    clock = Clock(datetime(2026, 1, 2, 3, 0, tzinfo=timezone.utc))
    meta = {"last_run_initialisation_time": 1767312000, "last_run_availability_time": 1767326400,
            "last_run_modification_time": 1767326000, "update_interval_seconds": 21600}
    status = {"code": 200}
    transport = lambda u, h, t, m: Response(u, status["code"], json.dumps(meta).encode())  # noqa: E731
    cfg = json.loads(json.dumps(CONFIG["families"]["fc1_openmeteo_meta"]))
    cfg["channels"]["run_meta"].update(models=["m_a", "m_b", "m_c"], daily_call_meter=4)
    channel = fc1_openmeteo_meta.build(cfg, LOCATIONS)[0]
    assert channel.quiet_local == (("12:00", "18:00"),)
    ctx = _ctx(tmp_path, "fc1_openmeteo_meta", transport, clock, channel="run_meta")
    channel.poll(ctx)
    channel.poll(ctx)
    status["code"] = 429
    clock.value += timedelta(days=1)
    channel.poll(ctx)
    ctx.journal.close()
    rows = _rows(tmp_path, "fc1_openmeteo_meta")
    assert sorted(r["key"] for r in rows) == ["m_a", "m_b", "m_c"]
    assert rows[0]["run_init"] == "2026-01-02T00:00:00Z" and rows[0]["provider_time"] == "2026-01-02T04:00:00Z"
    caps = [e["reason"] for e in _events(tmp_path, "fc1_openmeteo_meta") if e["kind"] == "cap"]
    caps += [e["reason"] for e in _events(tmp_path, "fc1_openmeteo_meta", "2026-01-03") if e["kind"] == "cap"]
    assert caps == ["daily_call_meter", "provider_429"]


# --------------------------------------------------------------------------------------------- FC-4
def _kmz(issue):
    kml = (f"<kml><dwd:IssueTime>{issue}</dwd:IssueTime><dwd:ForecastTimeSteps>"
           "<dwd:TimeStep>2026-01-02T10:00:00.000Z</dwd:TimeStep><dwd:TimeStep>2026-01-02T11:00:00.000Z</dwd:TimeStep>"
           "</dwd:ForecastTimeSteps><dwd:Forecast dwd:elementName=\"TTT\"><dwd:value>  280.15   281.05</dwd:value>"
           "</dwd:Forecast><dwd:Forecast dwd:elementName=\"TX\"><dwd:value>   -   285.00</dwd:value></dwd:Forecast>"
           "<dwd:Forecast dwd:elementName=\"FF\"><dwd:value> 1 2</dwd:value></dwd:Forecast></kml>")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("MOSMIX_L_2026010209_47671.kml", kml)
    return buffer.getvalue()


def test_mosmix_kmz_goes_to_cas_with_issue_time_run_identity(tmp_path):
    clock = Clock(datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc))
    kmz = _kmz("2026-01-02T09:00:00.000Z")
    cfg = json.loads(json.dumps(CONFIG["families"]["fc4_mosmix"]))
    cfg["stations"] = {"tokyo": "47671", "london": "P0478"}
    assert set(CONFIG["families"]["fc4_mosmix"]["stations"]) == {loc["id"] for loc in LOCATIONS}
    seen = []
    transport = lambda u, h, t, m: (seen.append(u), Response(u, 200 if "47671" in u else 404, kmz))[1]  # noqa: E731
    ctx = _ctx(tmp_path, "fc4_mosmix", transport, clock, channel="mosmix_l")
    fc4_mosmix.build(cfg, LOCATIONS)[0].poll(ctx)
    ctx.journal.close()
    assert any(u.endswith("/47671/kml/MOSMIX_L_LATEST_47671.kmz") for u in seen)
    (row,) = _rows(tmp_path, "fc4_mosmix")
    assert row["key"] == "47671|2026-01-02T09:00:00.000Z" and row["run_init"] == "2026-01-02T09:00:00.000Z"
    assert row["body"]["series"] == {"TTT": [280.15, 281.05], "TX": [None, 285.0]}
    assert read_raw(tmp_path, row["raw_ref"]) == kmz
    gaps = [e for e in _events(tmp_path, "fc4_mosmix") if e["kind"] == "gap"]
    assert [g["station"] for g in gaps] == ["P0478"]


# --------------------------------------------------------------------------------------------- VR-3
def _event(event_id, slug, source, price="0.5"):
    return {"id": event_id, "slug": slug, "title": slug, "resolutionSource": source, "negRisk": True,
            "markets": [{"id": "m1", "outcomePrices": f'["{price}", "0.5"]', "umaResolutionStatus": None}]}


def test_gamma_events_change_only_with_event_date_and_one_source_warning(tmp_path):
    clock = Clock(datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc))
    nyc = next(loc for loc in LOCATIONS if loc["id"] == "nyc")
    source = nyc["settlement"]["resolution_source_url"]
    replies = {"page": [_event("1", "highest-temperature-in-nyc-on-january-3-2026", source),
                        _event("2", "lowest-temperature-in-nyc-on-january-3-2026", "https://example.org/other")]}
    transport = lambda u, h, t, m: Response(u, 200, json.dumps(replies["page"] if "highest" in u else []).encode())  # noqa: E731
    channels = {c.name: c for c in vr3_gamma.build(CONFIG["families"]["vr3_gamma"], LOCATIONS)}
    assert channels["events_closed_sweep"].run_local == (("00:30", "01:00"),)
    ctx = _ctx(tmp_path, "vr3_gamma", transport, clock, channel="events_active")
    channels["events_active"].poll(ctx)
    channels["events_active"].poll(ctx)
    replies["page"][0] = _event("1", "highest-temperature-in-nyc-on-january-3-2026", source, price="0.6")
    channels["events_active"].poll(ctx)
    ctx.journal.close()
    rows = _rows(tmp_path, "vr3_gamma")
    assert [r["key"] for r in rows] == ["1", "2", "1"]
    assert {r["event_date"] for r in rows} == {"2026-01-03"}
    assert {r["body"]["series"] for r in rows} == {"highest", "lowest"}
    warns = [e for e in _events(tmp_path, "vr3_gamma") if e["kind"] == "warn"]
    assert len(warns) == 1 and warns[0]["event_id"] == "2"


@pytest.mark.parametrize("embargoed", [True, False], ids=["embargo-window", "open-days"])
def test_closed_sweep_runs_the_fetch_guard_before_any_request(tmp_path, embargoed):
    today = FULL_START + timedelta(days=5) if embargoed else FULL_START - timedelta(days=40)
    clock = Clock(datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(minutes=40))
    fetched = []
    transport = lambda u, h, t, m: (fetched.append(u), Response(u, 200, b"[]"))[1]  # noqa: E731
    sweep = {c.name: c for c in vr3_gamma.build(CONFIG["families"]["vr3_gamma"], LOCATIONS)}["events_closed_sweep"]
    ctx = _ctx(tmp_path, "vr3_gamma", transport, clock, channel="events_closed_sweep")
    sweep.poll(ctx)
    ctx.journal.close()
    guards = [e for e in _events(tmp_path, "vr3_gamma", today.isoformat()) if e["kind"] == "guard"]
    if embargoed:
        assert fetched == [] and len(guards) == 3
        assert {g["reason"] for g in guards} == {"fetch_event_date_embargoed"}
    else:
        assert guards == [] and len(fetched) == 3 * 2 * 51
        assert all("slug=" in u and "temperature-in-" in u for u in fetched)


def test_every_configured_family_builds_its_channels():
    built = {name: [c.name for c in load_family_channels(cfg, LOCATIONS)] for name, cfg in CONFIG["families"].items()}
    assert built["ob1_metar"] == ["metar_recent", "metar_sweep"]
    assert set(built) == {"ob1_metar", "ob2_nws", "ob3_native", "fc1_openmeteo_meta", "fc4_mosmix", "vr3_gamma"}
    optional = {name: [c.optional for c in load_family_channels(cfg, LOCATIONS)]
                for name, cfg in CONFIG["families"].items()}
    assert optional["ob1_metar"] == [False, True]
    assert all(all(flags) for name, flags in optional.items() if name != "ob1_metar")


def test_active_events_dated_in_a_full_window_are_never_journalled(tmp_path):
    clock = Clock(datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc))
    source = next(loc for loc in LOCATIONS if loc["id"] == "nyc")["settlement"]["resolution_source_url"]
    inside = FULL_START + timedelta(days=1)
    month = inside.strftime("%B").lower()
    events = [_event("1", f"highest-temperature-in-nyc-on-{month}-{inside.day}-{inside.year}", source),
              _event("2", "highest-temperature-in-nyc-on-january-3-2026", source)]
    transport = lambda u, h, t, m: Response(u, 200, json.dumps(events if "highest" in u else []).encode())  # noqa: E731
    active = {c.name: c for c in vr3_gamma.build(CONFIG["families"]["vr3_gamma"], LOCATIONS)}["events_active"]
    ctx = _ctx(tmp_path, "vr3_gamma", transport, clock, channel="events_active")
    active.poll(ctx)
    ctx.journal.close()
    assert [r["key"] for r in _rows(tmp_path, "vr3_gamma")] == ["2"]
