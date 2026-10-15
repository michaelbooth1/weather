"""``remaining_rise_pmf_v1`` builder: rise definition, kernel fold, determinism, reserved-window refusal.

Guards: remaining-rise 13-16 pre-registration §1 artifact definition (t3-r3, registry ae86d035...6559) and the
reserved-window boundary (no input row on or after 2026-09-30 is decoded; owner OD-B1 2026-10-15).
"""

import json
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from weather.calibration import remaining_rise_pmf as builder

TZ = "America/Chicago"
STATIONS = {"KTST": TZ}
SCHEMA = pa.schema([
    ("report_type", pa.string()),
    ("is_cor", pa.bool_()),
    ("tgroup_c", pa.float64()),
    ("main_temp_c", pa.float64()),
    ("available_utc", pa.timestamp("us", tz="UTC")),
    ("local_date", pa.date32()),
])


def _c(temp_f):
    return (temp_f - 32) / 1.8


def _profile(hour):
    return 70 + hour if hour <= 15 else 85 - (hour - 15)


def _day_rows(day, temp_of=_profile, hours=range(24)):
    rows = []
    for hour in hours:
        valid = datetime(day.year, day.month, day.day, hour, 53, tzinfo=ZoneInfo(TZ))
        rows.append({
            "report_type": "routine",
            "is_cor": False,
            "tgroup_c": _c(temp_of(hour)),
            "main_temp_c": round(_c(temp_of(hour))),
            "available_utc": valid + timedelta(minutes=10),
            "local_date": day,
        })
    return rows


def _write(path, rows, **kwargs):
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), path, **kwargs)


def _fixture_rows():
    day = date(2025, 6, 10)
    rows = _day_rows(day)
    rows[5]["tgroup_c"] = None  # body temperature fallback: round_half_up(23.888.. * 1.8 + 32) = 75
    rows[5]["main_temp_c"] = _c(75)
    hot = dict(rows[12], tgroup_c=_c(99))
    rows.append(dict(hot, is_cor=True))  # COR excluded
    rows.append(dict(hot, report_type="special"))  # non-routine excluded
    rows += _day_rows(date(2025, 6, 11), hours=range(5))  # incomplete day (< 20 routine rows)
    rows += _day_rows(date(2024, 4, 30), temp_of=lambda h: 100)  # before the history start
    return rows


def _kernel():
    weights = [math.exp(-0.5 * k * k) for k in range(-6, 7)]
    total = sum(weights)
    return [w / total for w in weights]


class TestRises:
    def test_rise_is_day_max_minus_running_max_available_at_h30(self, tmp_path):
        _write(tmp_path / "KTST.parquet", _fixture_rows())
        rises, complete = builder.station_rises(builder.load_station_rows(tmp_path / "KTST.parquet"), TZ)
        assert complete == 1
        assert (6, 0) not in rises  # nothing is available by 00:30
        # Row h (valid h:53) is available at (h+1):03, so at H:30 rows 0..H-1 count.
        for hour in range(1, 24):
            assert rises[(6, hour)] == [15 - min(hour - 1, 15)], hour

    def test_build_artifact_cells_and_inputs(self, tmp_path):
        _write(tmp_path / "KTST.parquet", _fixture_rows())
        document = builder.build_artifact(tmp_path, STATIONS)
        assert document["cell_count"] == 23
        assert document["inputs"][0]["complete_days"] == 1
        assert document["inputs"][0]["history_rows"] == 24 + 5
        cell = document["cells"]["KTST"]["6"]["1"]
        assert (cell["base"], cell["n_days"]) == (9, 1)
        assert cell["pmf"] == pytest.approx(_kernel(), abs=1e-15)

    def test_build_is_deterministic_and_cli_writes_canonical_bytes(self, tmp_path, capsys, monkeypatch):
        metar = tmp_path / "metar"
        metar.mkdir()
        _write(metar / "KTST.parquet", _fixture_rows())
        monkeypatch.setattr(builder.build_artifact, "__defaults__", (STATIONS,))
        out = tmp_path / "out.json"
        assert builder.main(["--metar-dir", str(metar), "--out", str(out)]) == 0
        printed = json.loads(capsys.readouterr().out)
        data = out.read_bytes()
        assert data == builder.canonical_bytes(builder.build_artifact(metar, STATIONS))
        assert printed["sha256"] == builder.sha256_bytes(data)
        assert data.endswith(b"\n") and b"\r" not in data


class TestKernel:
    def test_negative_tail_folds_onto_zero(self):
        base, pmf = builder.smooth_folded_pmf([0])
        kernel = _kernel()
        assert base == 0 and len(pmf) == 7
        assert pmf[0] == pytest.approx(sum(kernel[:7]), abs=1e-15)
        assert pmf[1:] == pytest.approx(kernel[7:], abs=1e-15)

    def test_unfolded_cell_keeps_negative_base_offset(self):
        base, pmf = builder.smooth_folded_pmf([10, 12, 12])
        assert base == 4 and len(pmf) == 15
        assert sum(pmf) == pytest.approx(1.0, abs=1e-12)

    def test_empty_cell_refused(self):
        with pytest.raises(ValueError):
            builder.smooth_folded_pmf([])


class TestReservedWindow:
    def test_last_pre_window_date_is_accepted(self, tmp_path):
        path = tmp_path / "KTST.parquet"
        _write(path, _day_rows(date(2026, 9, 29)))
        assert builder.load_station_rows(path) == {}  # outside history, but decodable

    def test_window_start_is_refused_before_decoding(self, tmp_path, monkeypatch):
        path = tmp_path / "KTST.parquet"
        _write(path, _day_rows(date(2025, 6, 10)) + _day_rows(date(2026, 9, 30), hours=range(1)))

        def no_decode(*_args, **_kwargs):
            raise AssertionError("rows were decoded")

        monkeypatch.setattr(pq, "read_table", no_decode)
        with pytest.raises(builder.ReservedWindowInput):
            builder.load_station_rows(path)

    def test_missing_statistics_are_refused(self, tmp_path):
        path = tmp_path / "KTST.parquet"
        _write(path, _day_rows(date(2025, 6, 10)), write_statistics=False)
        with pytest.raises(builder.ReservedWindowInput, match="statistics missing"):
            builder.load_station_rows(path)
