"""Lane L11 rung R-O: GEFS member point fetcher (tools/research/gefs_member_point_fetch.py).

Guards: the fetcher refuses dates after 2026-09-29, by default reads exactly the 06Z cycle's f006..f024 TMP 2 m
messages for gec00 + gep01..30 (the 18Z D-1 ap5 R-Q pass only when configured, then restored), locates one message
per idx, and interpolates bilinearly on the north-to-south grid.
"""
import datetime as dt
import importlib.util
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("gefs_fetch", ROOT / "tools" / "research" / "gefs_member_point_fetch.py")
gf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gf)


def test_plan_constants():
    assert gf.CYCLE_HOUR == 6 and gf.FHS == (6, 9, 12, 15, 18, 21, 24)
    assert gf.MEMBERS[0] == "gec00" and gf.MEMBERS[-1] == "gep30" and len(gf.MEMBERS) == 31
    assert gf.grib_key(dt.date(2021, 8, 1), "gep07", 9) == \
        "gefs.20210801/06/atmos/pgrb2sp25/gep07.t06z.pgrb2s.0p25.f009"


def test_refuses_dates_after_last_allowed():
    with pytest.raises(SystemExit):
        gf.date_list("2026-09-29..2026-09-30")
    assert gf.date_list("2026-09-28..2026-09-29") == [dt.date(2026, 9, 28), dt.date(2026, 9, 29)]


def test_idx_range_is_one_message():
    idx = "1:0:d=2021080106:GUST:surface:6 hour fcst:ENS=+1\n2:100:d=2021080106:TMP:2 m above ground:6 hour fcst:ENS=+1\n" \
          "3:250:d=2021080106:DPT:2 m above ground:6 hour fcst:ENS=+1\n"
    start, end, rec = gf.find_range(gf.parse_idx(idx), gf.VAR, 400)
    assert (start, end) == (100, 249) and rec.startswith("TMP:2 m above ground")


def test_bilinear_on_north_to_south_grid():
    field = np.zeros((721, 1440))
    j, i = np.meshgrid(np.arange(721), np.arange(1440), indexing="ij")
    lat, lon = 90.0 - 0.25 * j, 0.25 * i
    field[:] = 2.0 * lat + 0.5 * lon  # linear, so bilinear is exact
    c = gf.station_corners(33.6301, -84.4418)
    value, four = gf.bilinear(field, c)
    assert value == pytest.approx(2.0 * 33.6301 + 0.5 * ((-84.4418) % 360.0), abs=1e-9)
    assert len(four) == 4 and 0.0 <= c["wx"] < 1.0 and 0.0 <= c["wy"] < 1.0


def test_ap5_18z_configuration_and_default_restore():
    try:
        gf.configure(18, "ap5", (18, 21, 24, 27, 30, 33, 36), -1)
        assert gf.grib_key(dt.date(2021, 7, 31), "gep07", 18) == \
            "gefs.20210731/18/atmos/pgrb2ap5/gep07.t18z.pgrb2a.0p50.f018"
        c = gf.station_corners(33.6301, -84.4418)
        assert c["j1"] < 361 and c["i1"] < 720
        assert c["j0"] == int((90.0 - 33.6301) // 0.5)
    finally:
        gf.configure()
    assert gf.CYCLE_HOUR == 6 and gf.FHS == (6, 9, 12, 15, 18, 21, 24) and gf.GEFS_GRID["ni"] == 1440
    assert gf.grib_key(dt.date(2021, 8, 1), "gep07", 9).endswith("pgrb2sp25/gep07.t06z.pgrb2s.0p25.f009")
    with pytest.raises(SystemExit):
        gf.configure(18, "ap5", (18,), -2)
