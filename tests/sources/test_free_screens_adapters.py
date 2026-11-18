"""Free-source screen adapters (lane G): MRMS GRIB2 reader, slot picking, captured Open-Meteo fragments,
MOSMIX KMZ parser, RAOB site choice.

Guards: owner direction 2026-10-23 (lane G) that every screen reads dates <= 2026-09-29 only and uses no
paid source or account; sources AGENTS.md (no network in tests, explicit failure classification).
"""
from __future__ import annotations

import io
import json
import struct
import zipfile
from datetime import date, datetime, timezone

import numpy as np
import pytest
from PIL import Image

from weather.sources.free_screens import captured_openmeteo, common, forward_only, iem_raob, mrms


def _sm(v, nbytes):
    return struct.pack(">I" if nbytes == 4 else ">H", (abs(v) | (1 << (8 * nbytes - 1))) if v < 0 else v)


def _grib2(values_int, la1=40.0, lo1=270.0, step=0.5, R=-10.0, E=0, D=1, data_template=41):
    nj, ni = values_int.shape
    sec0 = b"GRIB" + b"\x00\x00" + b"\x00" + b"\x02"
    sec1 = struct.pack(">IB", 21, 1) + b"\x00" * 16
    s3 = bytearray(72)
    s3[0:5] = struct.pack(">IB", 72, 3)
    s3[12:14] = struct.pack(">H", 0)
    s3[30:38] = struct.pack(">II", ni, nj)
    s3[46:50] = _sm(int(la1 * 1e6), 4)
    s3[50:54] = _sm(int(lo1 * 1e6), 4)
    s3[63:67] = _sm(int(step * 1e6), 4)
    s3[67:71] = _sm(int(step * 1e6), 4)
    s5 = bytearray(21)
    s5[0:5] = struct.pack(">IB", 21, 5)
    s5[5:9] = struct.pack(">I", ni * nj)
    s5[9:11] = struct.pack(">H", data_template)
    s5[11:15] = struct.pack(">f", R)
    s5[15:17] = _sm(E, 2)
    s5[17:19] = _sm(D, 2)
    s5[19] = 16
    s6 = struct.pack(">IB", 6, 6) + b"\xff"
    png = io.BytesIO()
    Image.fromarray(values_int.astype(np.uint16)).save(png, format="PNG")
    s7 = struct.pack(">IB", 5 + len(png.getvalue()), 7) + png.getvalue()
    body = sec1 + bytes(s3) + bytes(s5) + s6 + s7 + b"7777"
    return sec0 + struct.pack(">Q", 16 + len(body)) + body


def test_mrms_reader_decodes_png_packing_and_scales_values():
    x = np.array([[0, 100, 500], [9990 - 990, 9990 + 450, 0]])
    values, meta = mrms.decode_grib2(_grib2(x))
    assert meta["ni"] == 3 and meta["nj"] == 2 and meta["lo1"] == 270.0 and meta["la1"] == 40.0
    assert values[0, 0] == pytest.approx(-1.0) and values[0, 2] == pytest.approx(49.0)
    assert values[1, 1] == pytest.approx(1043.0)


def test_mrms_reader_refuses_other_packings():
    with pytest.raises(ValueError, match="5.41"):
        mrms.decode_grib2(_grib2(np.zeros((2, 2)), data_template=42))
    with pytest.raises(ValueError, match="GRIB2"):
        mrms.decode_grib2(b"NOTGRIB" + b"\x00" * 20)


def test_extract_takes_the_max_inside_the_disk_and_skips_no_coverage():
    st = common.Station("x", "KX", "UTC", 40.0, -90.0)
    meta = {"la1": 40.5, "lo1": 269.5, "di": 0.01, "dj": 0.01, "ni": 101, "nj": 101}
    values = np.full((101, 101), -999.0, np.float32)
    values[50, 50] = 30.0                     # the station pixel
    values[50, 70] = 50.0                     # 0.2 deg east ~ 17 km: inside 25 km
    values[50, 100] = 60.0                    # 0.5 deg east ~ 43 km: only inside 50 km
    out = mrms.extract(values, meta, [st])["KX"]
    assert out["max_dbz_25km"] == 50.0 and out["max_dbz_50km"] == 60.0
    assert 0 < out["cover_25km"] < 1


def test_slot_picking_takes_the_newest_object_at_or_before_each_slot():
    keys = [f"CONUS/x/20240815/MRMS_x_20240815-{h:02d}{m:02d}40.grib2.gz" for h in (15, 16) for m in range(0, 60, 2)]
    picks = mrms.pick_slots(keys, date(2024, 8, 15))
    first = picks[0]
    assert first[0] == datetime(2024, 8, 15, 16, 0, tzinfo=timezone.utc)
    assert first[1] == datetime(2024, 8, 15, 15, 58, 40, tzinfo=timezone.utc)
    assert all(p[1] <= p[0] for p in picks) and len(picks) == 3   # 16:00, 16:30, 17:00 (16:58:40); none later


def test_mrms_default_days_end_on_the_last_development_day():
    days = mrms.default_days()
    assert max(days) == date(2026, 9, 29) and min(days) == date(2024, 8, 1)


def test_captured_openmeteo_reads_only_the_member_fragments():
    rec = {"snapshot_cadence_quality": {"snapshot_id": "wrong"}, "snapshot_id": "S1",
           "sources": {"global_ensemble": {"data": {"day_max_native": 81.5}},
                       "metar": {"data": {"day_max_native": 99.0}},
                       "open_meteo_global_models": {"data": {"day_model_highs": {"ecmwf_aifs025": None,
                                                                                 "ncep_aigfs025": 80.6}}},
                       "open_meteo_multimodel": {"data": {"day_model_highs": {"gfs_seamless": 85.6}}}}}
    row = captured_openmeteo.parse_line(json.dumps(rec, sort_keys=True))
    assert row == {"snapshot_id": "S1", "ecmwf_aifs025": None, "ncep_aigfs025": 80.6, "gfs_seamless": 85.6,
                   "gefs_mean": 81.5}
    assert captured_openmeteo.parse_event("highest-temperature-in-san-francisco-on-september-9-2026") == \
        ("san-francisco", "2026-09-09")


def test_mosmix_parser_reads_issue_time_and_converts_kelvin():
    kml = ('<?xml version="1.0"?><kml:kml xmlns:kml="http://www.opengis.net/kml/2.2" '
           'xmlns:dwd="https://opendata.dwd.de/weather/lib/pointforecast_dwd_extension_V1_0.xsd"><kml:Document>'
           '<kml:ExtendedData><dwd:ProductDefinition><dwd:IssueTime>2026-10-23T21:00:00.000Z</dwd:IssueTime>'
           '<dwd:ForecastTimeSteps><dwd:TimeStep>2026-10-23T22:00:00.000Z</dwd:TimeStep>'
           '<dwd:TimeStep>2026-10-23T23:00:00.000Z</dwd:TimeStep></dwd:ForecastTimeSteps></dwd:ProductDefinition>'
           '</kml:ExtendedData><kml:Placemark><kml:ExtendedData>'
           '<dwd:Forecast dwd:elementName="TTT"><dwd:value> 293.15 - </dwd:value></dwd:Forecast>'
           '<dwd:Forecast dwd:elementName="FF"><dwd:value> 1 2 </dwd:value></dwd:Forecast>'
           '</kml:ExtendedData></kml:Placemark></kml:Document></kml:kml>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.kml", kml)
    out = forward_only.parse_mosmix(buf.getvalue())
    assert out["issue_time"] == "2026-10-23T21:00:00.000Z" and len(out["steps"]) == 2
    assert out["elements"] == {"TTT": [20.0, None]}


def test_grib2_template_probe_reports_ccsds_packing():
    assert forward_only.grib2_templates(_grib2(np.zeros((2, 2)), data_template=42))["data_template"] == 42


def test_raob_sites_are_the_nearest_and_requests_stop_at_the_last_development_morning():
    sites = iem_raob.nearest_sites()
    assert sites["KDAL"][0] == "KFWD" and sites["KMIA"][0] == "KMFL" and sites["KBKF"][0] == "KDNR"
    assert iem_raob.END_UTC == datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc)
