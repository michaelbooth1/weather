"""Row 28 sentinel test v1 (lane L59): master's sealed-window ruling 1 (and ruling 2's guard), CLARIFICATION_2.md.

Calendar / synthetic only. It reads no real data: every input is built under pytest's tmp_path. It runs BEFORE the
controls stage and tests runner v3 (sha-pinned below):

1. A fake WU hourly month file for 2026-05 is written exactly as the WU writer writes it (wu_history.py 442:
   json.dumps(row, sort_keys=True) over normalize_observation's dict, 780-812). Lines dated 05-27..05-31 carry the
   sentinel 999.9 in every temperature, dewpoint, heat-index, wind-chill and humidity field, including the fields
   that sit BEFORE local_date in the raw line. The section 7 reader must skip exactly those lines (count correct),
   and the sentinel must appear in no output, no log and no exception message.
2. A line without the writer's prefix shape HALTs, and the HALT message carries no line content.
3. The runner's own daily_summary read filters on the raw line prefix: rows after 2025-12-31 (sentinel values) are
   skipped and counted, and the kept-lines sha256 covers the header and kept lines only.
4. The output guard: dates on or after 2026-01-01 are counted (never echoed) unless allowlisted; logs are withheld.

Route: scripts/ops/workstation_heavy.ps1 -Kind pytest -Queue, with an explicit --basetemp deleted afterwards.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import gzip  # noqa: E402
import hashlib  # noqa: E402
import importlib.util  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import pickle  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

import pytest  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
RUNNER = HERE / "row28_run_v3.py"
RUNNER_SHA256 = "949464ab987a746f9077294a96ef7cac511b55914f69f336bcded6c5b370c438"
SENTINEL = 999.9
SENTINEL_TEXT = "999.9"
TZ = ZoneInfo("America/Chicago")
TIMES = ((0, 52), (3, 52), (6, 52), (7, 0), (7, 52), (12, 52))  # six lines per day; 07:00 is the last <= 07:00
SEALED_DAYS = range(27, 32)
FORBIDDEN_DAY_TEXT = tuple(f"2026-05-{d:02d}" for d in SEALED_DAYS)


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def rt():
    assert _sha256(RUNNER) == RUNNER_SHA256, "runner v3 differs from the pinned sha256"
    if str(REPO / "src") not in sys.path:
        sys.path.insert(0, str(REPO / "src"))
    spec = importlib.util.spec_from_file_location("row28_run_v3_under_test", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _temp(day, hh, mm):
    return 50.0 + day + hh / 100.0 + mm / 10000.0


def _row(day, hh, mm):
    """One hourly row as the WU writer builds it; sealed days get the sentinel in every value field."""
    from weather.sources import wu_history

    local = datetime(2026, 5, day, hh, mm, tzinfo=TZ)
    t = _temp(day, hh, mm)
    obs = {"valid_time_gmt": int(local.timestamp()), "temp": t, "dewPt": t - 10.0, "heat_index": t, "wc": t,
           "rh": 50, "pressure": 29.92, "vis": 10, "wdir": 180, "wdir_cardinal": "S", "wspd": 5, "gust": None,
           "precip_hrly": 0.0, "precip_total": 0.0, "clds": "CLR", "wx_phrase": "Fair", "wx_icon": 31,
           "qualifier": None, "key": "KXXX", "obs_id": "KXXX", "obs_name": "Synthetic"}
    row = wu_history.normalize_observation(obs, TZ, unit="F")
    assert row is not None and row["local_date"] == f"2026-05-{day:02d}"
    if day in SEALED_DAYS:
        for key in ("temp_native", "temp_c", "dewpoint_native", "dewpoint_c", "heat_index_native", "heat_index_c",
                    "wind_chill_native", "wind_chill_c", "humidity"):
            row[key] = SENTINEL
    return row


def _write_month(root, rows_text):
    path = root / "data" / "wunderground" / "kxxx" / "hourly" / "year=2026" / "month=05" / "observations.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(line + "\n" for line in rows_text).encode("utf-8"))
    return path


def _assert_clean(text):
    assert SENTINEL_TEXT not in text
    for day in FORBIDDEN_DAY_TEXT:
        assert day not in text


def test_s7_reader_skips_sealed_lines_and_leaks_no_sentinel(rt, tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    lines = [json.dumps(_row(day, hh, mm), sort_keys=True) for day in range(1, 32) for hh, mm in TIMES]
    path = _write_month(tmp_path, lines)
    raw = path.read_bytes()
    assert raw.count(SENTINEL_TEXT.encode()) > 0  # the fixture really carries the sentinel, before local_date too
    first_sealed = next(line for line in lines if '"local_date": "2026-05-27"' in line)
    assert first_sealed.index(SENTINEL_TEXT) < first_sealed.index('"local_date"')

    cfg = {"main_data": str(tmp_path / "data")}
    out, skipped = rt.s7_wu_obs07(cfg, "kxxx", 2026, 5, "2026-05-06", "2026-05-26")

    assert skipped == len(SEALED_DAYS) * len(TIMES)  # 5 days x 6 lines = 30, and only those
    assert sorted(out) == [f"2026-05-{d:02d}" for d in range(6, 27)]
    assert out == {f"2026-05-{d:02d}": _temp(d, 7, 0) for d in range(6, 27)}  # last obs at or before 07:00
    assert all(abs(v - SENTINEL) > 1.0 for v in out.values())

    # What a stage writes from this reader (section7_gate writes aggregates and the count, never per-date rows):
    # through the guarded Writer, then the stage-end file guard.
    writer = rt.Writer(tmp_path / "run", tmp_path / "run" / "s7")
    (tmp_path / "run" / "s7").mkdir(parents=True)
    written = writer.json("s7_obs.json", {"obs07_values": sorted(out.values()), "n": len(out),
                                          "sealed_lines_skipped_undecoded": skipped})
    text = written.read_text(encoding="utf-8")
    _assert_clean(text)
    assert not rt.guard_file(written)

    captured = capsys.readouterr()
    _assert_clean(captured.out + captured.err)
    _assert_clean("\n".join(r.getMessage() for r in caplog.records))


def test_s7_reader_halts_without_the_writer_prefix_shape(rt, tmp_path):
    good = json.dumps(_row(10, 6, 52), sort_keys=True)
    unsorted = json.dumps(_row(28, 6, 52))  # not the writer's key order: the shape is absent
    _write_month(tmp_path, [good, unsorted])
    cfg = {"main_data": str(tmp_path / "data")}
    with pytest.raises(rt.Halt) as info:
        rt.s7_wu_obs07(cfg, "kxxx", 2026, 5, "2026-05-06", "2026-05-26")
    _assert_clean(str(info.value))


def test_daily_summary_prefix_filter(rt, tmp_path):
    header = ("schema_version,local_date,temperature_unit,row_count,first_time,last_time,max_temp,max_temp_native,"
              "max_temp_bucket,max_temp_bucket_native\r\n")
    kept = ["wu_daily_native_v1,2025-12-30,F,24,00:52,23:52,61.0,61.0,61,61\r\n",
            "wu_daily_native_v1,2025-12-31,F,23,00:52,23:52,62.0,62.0,62,62\r\n"]
    sealed = ["wu_daily_native_v1,2026-01-01,F,24,00:52,23:52,999.9,999.9,999.9,999.9\r\n",
              "wu_daily_native_v1,2026-05-28,F,24,00:52,23:52,999.9,999.9,999.9,999.9\r\n"]
    path = tmp_path / "daily_summary.csv"
    path.write_bytes((header + "".join(kept + sealed)).encode("utf-8"))
    out, info = rt.wu_daily_file(path, with_high=True)
    assert out == {"2025-12-30": (24, 61.0), "2025-12-31": (23, 62.0)}
    assert info["skipped_after_2025"] == 2 and info["kept_lines"] == 2
    assert info["kept_lines_sha256"] == hashlib.sha256((header + "".join(kept)).encode("utf-8")).hexdigest()
    _assert_clean(json.dumps([out, info]))
    bad = tmp_path / "bad.csv"
    bad.write_bytes((header + '"quoted,first",2025-12-30,F,24,a,b,1,1,1,1\r\n').encode("utf-8"))
    with pytest.raises(rt.Halt):
        rt.wu_daily_file(bad, with_high=False)


def test_output_guard_counts_and_never_echoes(rt, tmp_path):
    import numpy as np
    import pandas as pd

    none = frozenset()
    assert rt.guard_text("x 2026-05-27 y", none) == {"on_or_after_2026_05_27": 1}
    assert rt.guard_text("2026-03-01", none) == {"in_2026_before_05_27": 1}
    assert not rt.guard_text("2025-12-31 20261103T041500.000000-0500 12026-06-011", none)
    assert not rt.guard_text("C:\\x\\" + rt.GUARD_MASK_TOKEN + "\\scripts", none)
    assert not rt.guard_text("cap 2026-05-26")  # section 7's own constant, allowlisted
    allow = rt.set_guard_allowlist(SimpleNamespace(TEST_CENTRES=("2026-08-08",)))
    assert "2026-08-08" in allow and not rt.guard_text("centre 2026-08-08")
    frame = pd.DataFrame({"d": pd.to_datetime(["2025-01-01", "2026-06-01"]), "s": ["2025-01-02", "2025-01-03"],
                          "v": [1.0, 2.0]})
    assert rt.guard_obj(frame) == {"on_or_after_2026_05_27": 1}
    assert rt.guard_obj({"a": [np.datetime64("2026-07-01")]}) == {"on_or_after_2026_05_27": 1}
    p = tmp_path / "f.pkl.gz"
    p.write_bytes(gzip.compress(pickle.dumps(frame), mtime=0))
    assert rt.guard_file(p)["on_or_after_2026_05_27"] >= 1
    writer = rt.Writer(tmp_path / "run", tmp_path / "run" / "g")
    (tmp_path / "run" / "g").mkdir(parents=True)
    with pytest.raises(rt.Halt) as info:
        writer.json("x.json", {"d": "2026-05-29"})
    assert "2026-05-29" not in str(info.value) and not (tmp_path / "run" / "g" / "x.json").exists()
    writer.post_score = True
    assert writer.text("y.jsonl", b'{"d": "2026-05-30"}\n') is None and writer.withheld
    stream = rt.GuardedStream(io.StringIO())
    stream.write("obs 2026-05-28 " + SENTINEL_TEXT + "\n")
    stream.write("centre 2026-08-08\n")  # logs have no allowlist
    stream.write("ok 2025-12-31\n")
    assert stream.withheld == 2
    logged = stream.inner.getvalue()
    _assert_clean(logged)
    assert "2026-08-08" not in logged and "ok 2025-12-31" in logged
