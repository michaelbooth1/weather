"""Item 4 (owner 2026-10-02): METAR cadence, T-group tenths and SPECI retention."""

import json
from datetime import datetime, timedelta, timezone

from weather.sources import metar_reports
from weather.sources.metar_reports import (
    METAR_REPORT_CAPTURE_INTERVAL_SECONDS,
    append_new_reports,
    capture_due,
    capture_from_sources,
    ledger_path,
    metar_report_type,
    metar_row_annotations,
    parse_tgroup,
)

ROUTINE = {
    "icaoId": "KORD",
    "obsTime": 1790934660,  # 2026-10-02T09:51:00Z
    "reportTime": "2026-10-02T10:00:00.000Z",
    "receiptTime": "2026-10-02T09:54:12.000Z",
    "metarType": "METAR",
    "temp": -1.1,
    "dewp": -5.6,
    "rawOb": "METAR KORD 020951Z 27010KT 10SM FEW250 M01/M06 A3012 RMK AO2 SLP205 T10111056",
}
SPECI = {
    "icaoId": "KORD",
    "obsTime": 1790935800,  # 2026-10-02T10:10:00Z
    "reportTime": "2026-10-02T10:10:00.000Z",
    "metarType": "SPECI",
    "temp": 0.6,
    "dewp": None,
    "rawOb": "SPECI KORD 021010Z 28012G20KT 3SM -SN BKN008 01/M05 A3013 RMK AO2 T0006",
}


def test_capture_cadence_is_inside_owner_range():
    assert 120.0 <= METAR_REPORT_CAPTURE_INTERVAL_SECONDS <= 300.0
    now = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    assert capture_due(None, now)
    assert not capture_due(now - timedelta(seconds=60), now)
    assert capture_due(now - timedelta(seconds=METAR_REPORT_CAPTURE_INTERVAL_SECONDS), now)


def test_tgroup_parses_positive_negative_and_missing_parts():
    assert parse_tgroup("KATL 021452Z 21008KT 28/20 A3000 RMK AO2 T02830200") == (28.3, 20.0)
    assert parse_tgroup(ROUTINE["rawOb"]) == (-1.1, -5.6)
    assert parse_tgroup("KSEA 020953Z 00000KT M00/M02 RMK AO2 T10021017") == (-0.2, -1.7)
    assert parse_tgroup(SPECI["rawOb"]) == (0.6, None)
    assert parse_tgroup("KLAX 020953Z 25005KT 18/12 A2992 RMK AO2 SLP131") == (None, None)
    # A body token shaped like a T-group is never read; only RMK is searched.
    assert parse_tgroup("KXYZ 020953Z T02830200 18/12 A2992") == (None, None)
    assert parse_tgroup(None) == (None, None)


def test_report_type_prefers_provider_field_then_raw_prefix():
    assert metar_report_type(ROUTINE) == "METAR"
    assert metar_report_type(SPECI) == "SPECI"
    assert metar_report_type({"rawOb": "SPECI KORD 021010Z RMK AO2"}) == "SPECI"
    assert metar_report_type({"rawOb": "KORD 021010Z RMK AO2"}) is None
    annotations = metar_row_annotations(SPECI)
    assert annotations["report_type"] == "SPECI"
    assert annotations["obs_time_utc"] == "2026-10-02T10:10:00+00:00"
    assert annotations["tgroup_temp_celsius"] == 0.6


def test_ledger_keeps_speci_dedups_and_stamps_first_seen(tmp_path):
    first = datetime(2026, 10, 2, 10, 12, tzinfo=timezone.utc)
    assert append_new_reports(tmp_path, "chicago", "KORD", [ROUTINE, SPECI], first) == 2
    later = first + timedelta(minutes=2)
    assert append_new_reports(tmp_path, "chicago", "KORD", [ROUTINE, SPECI], later) == 0

    path = ledger_path(tmp_path, "chicago", "2026-10-02")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [record["report_type"] for record in records] == ["METAR", "SPECI"]
    assert all(record["first_seen_at_utc"] == first.isoformat() for record in records)
    assert records[0]["schema_version"] == "metar_report_ledger_v0.1"
    assert records[0]["tgroup_temp_celsius"] == -1.1
    assert records[0]["provider_temp_celsius"] == -1.1
    assert records[1]["tgroup_dewpoint_celsius"] is None
    assert records[1]["raw"] == SPECI["rawOb"]


def test_capture_from_sources_gates_cadence_and_refuses_stale(tmp_path):
    gate = {}
    now = datetime(2026, 10, 2, 10, 12, tzinfo=timezone.utc)
    fresh = {"metar": {"ok": True, "stale": False, "data": {"raw_payload": [ROUTINE]}}}

    result = capture_from_sources(tmp_path, "chicago", "KORD", fresh, now, last_capture_at=gate)
    assert result["status"] == "captured" and result["appended"] == 1

    with_speci = {"metar": {"ok": True, "data": {"raw_payload": [ROUTINE, SPECI]}}}
    early = capture_from_sources(
        tmp_path, "chicago", "KORD", with_speci, now + timedelta(seconds=60), last_capture_at=gate,
    )
    assert early["status"] == "not_due"
    due = capture_from_sources(
        tmp_path, "chicago", "KORD", with_speci, now + timedelta(seconds=120), last_capture_at=gate,
    )
    assert due["status"] == "captured" and due["appended"] == 1

    stale = {"metar": {"ok": True, "stale": True, "data": {"raw_payload": [ROUTINE]}}}
    assert capture_from_sources(
        tmp_path / "other", "chicago", "KORD", stale, now, last_capture_at={},
    )["status"] == "skipped_not_fresh"
    assert not (tmp_path / "other").exists()
    assert capture_from_sources(tmp_path, "toronto", "CYYZ", {}, now, last_capture_at={})["status"] == "not_configured"


def test_capture_errors_are_returned_not_raised(tmp_path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(metar_reports, "append_new_reports", boom)
    sources = {"metar": {"ok": True, "data": {"raw_payload": [ROUTINE]}}}
    result = capture_from_sources(
        tmp_path, "chicago", "KORD", sources, datetime(2026, 10, 2, tzinfo=timezone.utc), last_capture_at={},
    )
    assert result["status"] == "error"
    assert "disk full" in result["error"]
