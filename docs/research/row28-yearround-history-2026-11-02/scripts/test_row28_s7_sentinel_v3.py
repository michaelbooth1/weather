"""Row 28 sentinel test v3 (lane L59): master's sealed-window ruling 1, ruling 2's guard as scoped by the v4 rulings,
the v3 delta review F1-F9 and the v4 delta review G1-G3 / item 9 (RUN_LOG.md, CLARIFICATION_2.md, CLARIFICATION_3.md).

Calendar / synthetic only. It reads no real data: every input is built under pytest's tmp_path (the runner's
module constants and pooled_residual_model's centre constants are imported; nothing else is read). It runs BEFORE
the controls stage and tests runner v5 (sha-pinned below); v1 (runner v3) and v2 (runner v4) are kept unchanged.

1. A fake WU hourly month file for 2026-05 is written exactly as the WU writer writes it (wu_history.py 442:
   json.dumps(row, sort_keys=True) over normalize_observation's dict, 780-812). Lines dated 05-27..05-31 carry the
   sentinel 999.9 in every temperature, dewpoint, heat-index, wind-chill and humidity field, including the fields
   that sit BEFORE local_date in the raw line. The section 7 reader must skip exactly those lines (count correct),
   and the sentinel must appear in no output, no log and no exception message.
2. A line without the writer's prefix shape HALTs, and the HALT message carries no line content.
3. The runner's own daily_summary read filters on the raw line prefix: rows after 2025-12-31 (sentinel values) are
   skipped and counted, and the kept-lines sha256 covers the header and kept lines only.
   F8: "undecoded" is tested for real: the reader's open and json.loads are wrapped, and no decode or parse call ever
   sees a sealed line.
4. The output guard (v4, context-scoped, F3): dates on or after 2026-01-01 are counted, never echoed. A sealed centre
   label passes only as the whole value of a centre field and only if it is an arm centre; the same label in a
   free-text or non-centre field, as an undeclared dict key, or in a log other than an exact centre=<label> token is
   a HIT. Section 7's constants pass only in section 7's declared fields; the records generated_at path passes only
   in records files with a pinned value; record names pass only as declared fields/keys or under records_root.
   F1: a pickle of many DataFrames whose last holds a 2026 datetime64 column is a HIT. F3 f: the byte cross-check
   catches a dated string the walk cannot see. After a score exists a hit withholds the file and the arms become
   INCOMPLETE (ruling 1, F5). F4: verify_prev needs a COMPLETE, guard-clean receipt. F9: score_folds failures carry
   a code only. v5: G1 the Writer serialises first and byte-checks before writing (an unused 2026 category or a
   dated dtype field name is withheld after a score and never reaches disk); G2 verify_prev binds the receipt to
   its report; G3 generated_at must be its own market's pin; item 9 B within A and B_*centre* fields use B's set.

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
RUNNER = HERE / "row28_run_v5.py"
RUNNER_SHA256 = "e138d9af14476ef918cc1768b1589c2ac5e95d8faf18ac32eeff308d149d7d32"
SENTINEL = 999.9
SENTINEL_TEXT = "999.9"
TZ = ZoneInfo("America/Chicago")
TIMES = ((0, 52), (3, 52), (6, 52), (7, 0), (7, 52), (12, 52))  # six lines per day; 07:00 is the last <= 07:00
SEALED_DAYS = range(27, 32)
FORBIDDEN_DAY_TEXT = tuple(f"2026-05-{d:02d}" for d in SEALED_DAYS)
SEALED_LABEL = "2026-06-07"   # a JAN_JUL centre label inside the sealed window 05-27..07-30 (master, v4 ruling 2)
FORWARD_LABEL = "2026-12-24"  # an OCT_DEC centre label on or after 09-30
RECORDS_ROOT = r"C:\t\L59\row28\run\records"  # the configured records_root (a string only; nothing is opened)
PINNED_AT = "2026-06-07T22:08:48"  # calibrated_weights_atlanta.json metadata.generated_at (F2 pin)
SEALED = {"on_or_after_2026_05_27": 1}


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def rt():
    assert _sha256(RUNNER) == RUNNER_SHA256, "runner v5 differs from the pinned sha256"
    if str(REPO / "src") not in sys.path:
        sys.path.insert(0, str(REPO / "src"))
    spec = importlib.util.spec_from_file_location("row28_run_v5_under_test", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    centres = _centres()
    assert mod.set_guard_centres(centres, RECORDS_ROOT) == {"sha256": mod.GUARD_CENTRE_SET_SHA256, "count": 24}
    assert SEALED_LABEL in centres["A"] and FORWARD_LABEL in centres["A"]
    return mod


def _centres():
    from weather.calibration import pooled_residual_model as prm  # constants only; no data is read

    centres = {"A": tuple(prm.FORWARD_CENTRES) + tuple(prm.JAN_JUL_CENTRES) + ("2026-12-24",),
               "B": tuple(prm.JAN_JUL_CENTRES[:10]) + ("2026-12-24",)}
    centres["C"] = centres["D"] = centres["A"]
    return centres


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


def test_s7_reader_never_decodes_a_sealed_line(rt, tmp_path, monkeypatch):
    """F8: wrap the reader's open (each raw line becomes a bytes subclass that records decode calls) and json.loads;
    no decode and no parse ever sees a sealed line, and only in-window lines at or before 07:00 are decoded."""
    lines = [json.dumps(_row(day, hh, mm), sort_keys=True) for day in range(1, 32) for hh, mm in TIMES]
    _write_month(tmp_path, lines)
    decoded, parsed = [], []

    class SpyBytes(bytes):
        def decode(self, *args, **kwargs):
            decoded.append(bytes(self))
            return bytes.decode(self, *args, **kwargs)

    class SpyHandle:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.handle.close()

        def __iter__(self):
            return (SpyBytes(line) for line in self.handle)

    real_open, real_json = open, rt.json

    def spy_open(path, mode="r", *args, **kwargs):
        handle = real_open(path, mode, *args, **kwargs)
        return SpyHandle(handle) if "b" in mode else handle

    def spy_loads(text, *args, **kwargs):
        parsed.append(text)
        return real_json.loads(text, *args, **kwargs)

    monkeypatch.setattr(rt, "open", spy_open, raising=False)
    monkeypatch.setattr(rt, "json", SimpleNamespace(loads=spy_loads, dumps=real_json.dumps))
    out, skipped = rt.s7_wu_obs07({"main_data": str(tmp_path / "data")}, "kxxx", 2026, 5, "2026-05-06", "2026-05-26")
    assert skipped == len(SEALED_DAYS) * len(TIMES)
    assert len(out) == 21
    assert len(decoded) == len(parsed) == 21 * 4  # days 06..26, the four lines at or before 07:00
    for line in decoded:
        assert SENTINEL_TEXT.encode() not in line and not any(d.encode() in line for d in FORBIDDEN_DAY_TEXT)
    for text in parsed:
        assert SENTINEL_TEXT not in text and not any(d in text for d in FORBIDDEN_DAY_TEXT)


def test_output_guard_counts_and_never_echoes(rt, tmp_path):
    import numpy as np
    import pandas as pd

    assert rt.guard_text("x 2026-05-27 y") == {"on_or_after_2026_05_27": 1}
    assert rt.guard_text("2026-03-01") == {"in_2026_before_05_27": 1}
    assert not rt.guard_text("2025-12-31 20261103T041500.000000-0500 12026-06-011")
    assert not rt.guard_text("C:\\x\\" + rt.GUARD_MASK_TOKEN + "\\scripts")
    frame = pd.DataFrame({"d": pd.to_datetime(["2025-01-01", "2026-06-01"]), "s": ["2025-01-02", "2025-01-03"],
                          "v": [1.0, 2.0]})
    assert rt.guard_obj(frame) == SEALED
    assert rt.guard_obj({"a": [np.datetime64("2026-07-01")]}) == SEALED
    p = tmp_path / "f.pkl.gz"
    p.write_bytes(gzip.compress(pickle.dumps(frame), mtime=0))
    assert rt.guard_file(p)["on_or_after_2026_05_27"] >= 1


def test_f1_many_frames_in_one_pickle(rt, tmp_path):
    """F1: walk temporaries are kept alive, so a later DataFrame column is never skipped by a reused id."""
    import pandas as pd

    frames = [pd.DataFrame({"market": ["atlanta"] * 3, "target_date": ["2024-01-0%d" % (i % 9 + 1)] * 3,
                            "y": [float(i)] * 3}) for i in range(60)]
    frames.append(pd.DataFrame({"market": ["austin"], "when": pd.to_datetime(["2026-07-01"]), "y": [1.0]}))
    assert rt.guard_obj(frames) == SEALED
    assert rt.guard_obj({"a": frames[0], "b": frames[-1]}) == SEALED
    p = tmp_path / "two.pkl.gz"
    p.write_bytes(gzip.compress(pickle.dumps([frames[0], frames[-1]]), mtime=0))
    assert rt.guard_file(p) == SEALED


def test_f3f_byte_crosscheck(rt, tmp_path):
    """F3 f: a dated string inside a pickle that the structural walk cannot see (a structured dtype's field name, a
    float Series' name) is caught by the raw-byte count. v5 G1: unused categorical categories ARE walked now."""
    import numpy as np
    import pandas as pd

    frame = pd.DataFrame({"note": pd.Categorical(["a", "a"], categories=["a", SEALED_LABEL])})
    assert rt.guard_obj(frame) == SEALED  # G1: the unused category is walked
    assert rt.guard_obj(pd.CategoricalIndex(["a"], categories=["a", SEALED_LABEL])) == SEALED
    assert rt.guard_obj(pd.DataFrame([[1.0]], columns=pd.CategoricalIndex(["a"], categories=["a", SEALED_LABEL])))
    assert not rt.guard_obj(pd.DataFrame({"centre": pd.Categorical(["2026-01-08"], categories=["2026-01-08",
                                                                                                SEALED_LABEL])}))
    p = tmp_path / "cat.pkl.gz"
    p.write_bytes(gzip.compress(pickle.dumps(frame), mtime=0))
    assert rt.guard_file(p) == SEALED
    for hidden in (np.zeros(2, dtype=[(SEALED_LABEL, "f8")]), pd.Series([1.0], name=SEALED_LABEL)):
        assert not rt.guard_obj(hidden)
        q = tmp_path / "hidden.pkl.gz"
        q.write_bytes(gzip.compress(pickle.dumps(hidden), mtime=0))
        assert rt.guard_file(q) == {"byte_crosscheck": 1}
    ok = tmp_path / "ok.pkl.gz"
    ok.write_bytes(gzip.compress(pickle.dumps(pd.DataFrame({"centre": [SEALED_LABEL] * 3})), mtime=0))
    assert not rt.guard_file(ok)


def test_g1_writer_checks_serialised_bytes_before_writing(rt, tmp_path):
    """G1: post-score, an unused 2026 category (walk) and a dated dtype field name (bytes only) are withheld and NOT
    on disk; pre-score the same outputs HALT before anything is written."""
    import numpy as np
    import pandas as pd

    stage = tmp_path / "run" / "g1"
    stage.mkdir(parents=True)
    frame = pd.DataFrame({"note": pd.Categorical(["a"], categories=["a", "2026-06-01"])})
    hidden = {"arr": np.zeros(1, dtype=[("2026-06-02", "f8")])}
    pre = rt.Writer(tmp_path / "run", stage)
    for name, obj in (("cat.pkl.gz", frame), ("hid.pkl.gz", hidden)):
        with pytest.raises(rt.Halt) as info:
            pre.pickle_gz(name, obj)
        assert "2026-06-0" not in str(info.value) and not (stage / name).exists()
    w = rt.Writer(tmp_path / "run", stage)
    w.post_score = True
    assert w.pickle_gz("cat.pkl.gz", frame) is None and not (stage / "cat.pkl.gz").exists()
    assert w.pickle_gz("hid.pkl.gz", hidden) is None and not (stage / "hid.pkl.gz").exists()
    assert [e["hits"] for e in w.withheld] == [SEALED, {"byte_crosscheck": 1}]
    assert "2026-06-0" not in json.dumps(w.withheld) and not w.written
    assert w.json("fine.json", {"centre": SEALED_LABEL, "n": 3}) is not None and (stage / "fine.json").exists()
    assert w.gz_json("fine.json.gz", {"x": "2025-12-31"}) is not None
    assert w.jsonl("fine.jsonl", [{"centre": FORWARD_LABEL}]) is not None



def test_centre_label_passes_only_as_a_centre_field_value(rt):
    # The same sealed label: a centre field value passes; anywhere else it is a HIT.
    assert not rt.guard_obj({"centre": SEALED_LABEL})
    assert not rt.guard_obj({"payload_centre": SEALED_LABEL, "rule_l_2024_02_29": SEALED_LABEL,
                             "x_centre": FORWARD_LABEL})
    assert not rt.guard_obj([{"centre": SEALED_LABEL, "years": [2021, 2022]}])
    assert rt.guard_obj({"note": SEALED_LABEL}) == SEALED
    assert rt.guard_obj({"reason": "centre " + SEALED_LABEL + ": failed"}) == SEALED  # free text
    assert rt.guard_obj({"reason": "centre=" + SEALED_LABEL}) == SEALED  # the log token rule is for logs only
    assert rt.guard_obj({"centre": "centre " + SEALED_LABEL}) == SEALED  # not the WHOLE value
    assert rt.guard_obj({"centre": SEALED_LABEL + " "}) == SEALED
    assert rt.guard_obj({SEALED_LABEL: [2021]}) == SEALED  # an undeclared dict key
    assert rt.guard_obj({"covered_years": {SEALED_LABEL: [2021]}}) == SEALED
    assert not rt.guard_obj({"by_centre": {SEALED_LABEL: [2021]}})  # F3 c: a declared parent
    assert rt.guard_obj({"by_centre": {"2026-06-08": [2021]}}) == SEALED
    assert rt.guard_obj({"season": SEALED_LABEL}) == SEALED  # season values are names, never dates
    assert rt.guard_obj([SEALED_LABEL]) == SEALED  # no field at all
    assert rt.guard_obj({"error": ["atlanta", SEALED_LABEL, "x"]}) == SEALED
    assert rt.guard_text(SEALED_LABEL) == SEALED and not rt.guard_text(SEALED_LABEL, field="centre")
    # A label outside the arm centre set is a HIT even in a centre field.
    assert rt.guard_obj({"centre": "2026-06-08"}) == SEALED
    assert rt.guard_obj({"centre": "2026-03-01"}) == {"in_2026_before_05_27": 1}
    assert rt.guard_obj({"centre": FORWARD_LABEL, "note": FORWARD_LABEL}) == SEALED
    # Nested: the nearest string key decides; a list under a centre key inherits it.
    assert not rt.guard_obj({"x": {"centre": [SEALED_LABEL, FORWARD_LABEL]}})
    assert rt.guard_obj({"centre": {"note": SEALED_LABEL}}) == SEALED
    assert rt.centre_tag(SimpleNamespace(centres={"A": (SEALED_LABEL,)}), SEALED_LABEL) == "centre#0"
    # The report keeps the centre set as a sha256 and a count only (F3 b).
    assert not hasattr(rt, "set_guard_allowlist")


def test_log_centre_token_rule(rt):
    """F3 h: logs mask only the folder-name token and an exact centre=<arm label> token (the launcher is identical)."""
    assert not rt.guard_log_text("extracted atlanta centre=" + SEALED_LABEL)
    assert not rt.guard_log_text("centre=" + SEALED_LABEL + ", centre=" + FORWARD_LABEL + "\n")
    assert rt.guard_log_text("centre=2026-06-08") == SEALED  # not an arm centre
    assert rt.guard_log_text("centre " + SEALED_LABEL) == SEALED
    assert rt.guard_log_text("centre: " + SEALED_LABEL) == SEALED
    assert rt.guard_log_text("xcentre=" + SEALED_LABEL) == SEALED
    assert rt.guard_log_text("centre=" + SEALED_LABEL + "x") == SEALED
    assert rt.guard_log_text("centre=" + SEALED_LABEL + "-01") == SEALED
    assert rt.guard_log_text("payload_centre=" + SEALED_LABEL) == SEALED
    assert rt.guard_log_text("date=" + SEALED_LABEL) == SEALED
    assert rt.guard_log_text("records_atlanta_" + SEALED_LABEL + ".pkl.gz") == SEALED  # logs: no record-name mask
    assert rt.LOG_CENTRE_TOKEN == "(?<![A-Za-z0-9_])centre=(20[0-9]{2}-[01][0-9]-[0-3][0-9])(?![0-9A-Za-z_-])"
    stream = rt.GuardedStream(io.StringIO())
    stream.write("obs 2026-05-28 " + SENTINEL_TEXT + "\n")
    stream.write("centre " + SEALED_LABEL + "\n")
    stream.write("built centre=" + SEALED_LABEL + "\n")
    stream.write("ok 2025-12-31\n")
    assert stream.withheld == 2
    logged = stream.inner.getvalue()
    _assert_clean(logged)
    assert "ok 2025-12-31" in logged and "built centre=" + SEALED_LABEL in logged
    assert ("centre " + SEALED_LABEL) not in logged


def test_centre_label_in_frames_and_files(rt, tmp_path):
    import pandas as pd

    ok = pd.DataFrame({"market": ["atlanta", "austin"], "centre": [SEALED_LABEL, FORWARD_LABEL],
                       "target_date": ["2023-06-07", "2024-12-24"], "y": [1.0, 2.0]})
    assert not rt.guard_obj(ok)
    assert not rt.guard_obj(ok.assign(centre=pd.to_datetime(ok["centre"])))  # datetime centre column
    assert rt.guard_obj(ok.assign(label=[SEALED_LABEL, "2025-01-01"])) == SEALED  # non-centre column
    assert rt.guard_obj(ok.assign(target_date=[SEALED_LABEL, "2024-12-24"])) == SEALED
    assert not rt.guard_obj(ok.set_index("centre"))  # an index named centre
    assert rt.guard_obj(ok.set_index("market").T)  # transposed: the labels sit under market-named columns

    d = tmp_path / "files"
    d.mkdir()
    (d / "a.json").write_text(json.dumps({"covered_years": [{"centre": SEALED_LABEL, "years": [2021]}]}))
    (d / "b.json").write_text(json.dumps({"covered_years": {SEALED_LABEL: [2021]}}))
    (d / "c.jsonl").write_text(json.dumps({"centre": SEALED_LABEL}) + "\n" + json.dumps({"d": SEALED_LABEL}) + "\n")
    (d / "d.csv").write_text("market,centre,note\natlanta," + SEALED_LABEL + ",x\naustin," + FORWARD_LABEL + ","
                             + SEALED_LABEL + "\n")
    (d / "d2.csv").write_text("market,centre\natlanta," + SEALED_LABEL + "\n")
    (d / "e.txt").write_text("centre " + SEALED_LABEL + "\n")
    (d / "f.json.gz").write_bytes(b"not gzip")
    assert not rt.guard_file(d / "a.json")
    assert rt.guard_file(d / "b.json") == SEALED
    assert rt.guard_file(d / "c.jsonl") == SEALED
    assert rt.guard_file(d / "d.csv") == SEALED
    assert not rt.guard_file(d / "d2.csv")
    assert rt.guard_file(d / "e.txt") == SEALED  # unstructured text: no exception
    assert rt.guard_file(d / "f.json.gz") == {"unscannable": 1}


def test_section7_constants_pass_only_in_section7_fields(rt):
    """F3 i: only S7_CONSTANT_FIELDS ("cap") inside the v5_gate_section7 subtree may hold a section 7 constant."""
    assert rt.S7_CONSTANT_FIELDS == ("cap",)
    assert not rt.guard_obj({"v5_gate_section7": {"cap": "2026-05-26", "n": {"V5": 3}}})
    assert rt.guard_obj({"cap": "2026-05-26"}) == {"in_2026_before_05_27": 1}  # outside section 7
    assert rt.guard_obj({"v5_gate_section7": {"window": ["2026-01-01"]}}) == {"in_2026_before_05_27": 1}
    assert rt.guard_obj({"v5_gate_section7": {"cap": "read cap 2026-05-26"}}) == {"in_2026_before_05_27": 1}
    assert rt.guard_obj({"v5_gate_section7": {"cap": "2026-05-27"}}) == SEALED
    assert rt.guard_obj({"v5_gate_section7": {"cap": "2026-02-01"}}) == {"in_2026_before_05_27": 1}
    assert not rt.guard_text("2026-05-05", field="cap", in_s7=True) and rt.guard_text("2026-05-05", in_s7=True)


def test_records_generated_at_and_names(rt, tmp_path):
    """F2 and F3 a."""
    payload = {"market": "atlanta", "centre": SEALED_LABEL,
               "calibrated_weights": {"metadata": {"generated_at": PINNED_AT}, "w": [0.1]}}
    assert PINNED_AT in rt.RECORDS_GENERATED_AT_VALUES and len(rt.CALIBRATED_WEIGHTS_PINS) == 12
    assert not rt.guard_obj(payload, records_file=True)
    assert rt.guard_obj(payload) == SEALED  # only in records files
    unpinned = {"calibrated_weights": {"metadata": {"generated_at": "2026-06-07T22:08:49"}}}
    assert rt.guard_obj(unpinned, records_file=True) == SEALED  # the value is pinned too
    moved = {"calibrated_weights": {"generated_at": PINNED_AT}, "meta": {"generated_at": PINNED_AT}}
    assert rt.guard_obj(moved, records_file=True) == {"on_or_after_2026_05_27": 2}  # the exact path only
    assert rt.guard_obj({"x": payload}, records_file=True) == SEALED  # top-level path only
    name = "records_atlanta_" + SEALED_LABEL + ".pkl.gz"
    p = tmp_path / name
    p.write_bytes(gzip.compress(pickle.dumps(payload), mtime=0))
    assert not rt.guard_file(p)
    q = tmp_path / ("other_" + SEALED_LABEL + ".pkl.gz")
    q.write_bytes(gzip.compress(pickle.dumps(payload), mtime=0))
    assert rt.guard_file(q) == SEALED  # not a records file: generated_at is a hit
    # Record names: under records_root, as the whole value of "file", or as a key under "records_sha256" only.
    assert not rt.guard_text(RECORDS_ROOT + "\\" + name)
    assert not rt.guard_text(RECORDS_ROOT.replace("\\", "/") + "/" + name)
    assert not rt.guard_text(RECORDS_ROOT.lower() + "\\" + name)
    assert not rt.guard_obj({"outputs_sha256": {RECORDS_ROOT + "\\" + name: "ab"}})
    assert not rt.guard_obj({"payload_meta": [{"file": name, "centre": SEALED_LABEL}]})
    assert not rt.guard_obj({"records_sha256": {name: "ab"}})
    assert rt.guard_obj({"other_sha256": {name: "ab"}}) == SEALED
    assert rt.guard_obj({"note": name}) == SEALED
    assert rt.guard_text(name) == SEALED  # a bare name in free text
    assert rt.guard_text("C:\\t\\L59\\row28\\run\\build\\" + name) == SEALED  # not under records_root
    assert rt.guard_text(RECORDS_ROOT + "\\records_atlantis_" + SEALED_LABEL + ".pkl.gz") == SEALED
    assert rt.guard_text(RECORDS_ROOT + "\\records_atlanta_2026-06-08.pkl.gz") == SEALED  # not an arm centre
    assert rt.guard_text(RECORDS_ROOT + "\\" + name + ".bak") == SEALED
    assert rt.guard_obj({"file": "x" + name}) == SEALED
    assert rt.name_tag(name).startswith("name#") and SEALED_LABEL not in rt.name_tag(name)


def test_writer_halt_withhold_and_incomplete(rt, tmp_path):
    writer = rt.Writer(tmp_path / "run", tmp_path / "run" / "g")
    (tmp_path / "run" / "g").mkdir(parents=True)
    with pytest.raises(rt.Halt) as info:
        writer.json("x.json", {"note": SEALED_LABEL})
    assert SEALED_LABEL not in str(info.value) and not (tmp_path / "run" / "g" / "x.json").exists()
    assert writer.json("ok.json", {"centre": SEALED_LABEL}) is not None
    assert writer.jsonl("ok.jsonl", [{"centre": SEALED_LABEL}, {"centre": FORWARD_LABEL}]) is not None
    writer.post_score = True
    assert writer.jsonl("rows.jsonl", [{"d": "2026-05-30"}]) is None and writer.withheld
    assert not (tmp_path / "run" / "g" / "rows.jsonl").exists()
    assert "2026-05-30" not in json.dumps(writer.withheld)

    look = {"look": {"A": {"point": 0.1, "futile": False}, "B": {"status": "HALTED"},
                     "C": {"point": 0.2, "futile": True}, "D": {"point": 0.0}}}
    rt.apply_incomplete(look, "r")
    assert look["look"]["B"] == {"status": "HALTED"}
    assert {a for a, v in look["look"].items() if v.get("status") == "INCOMPLETE"} == {"A", "C", "D"}
    assert look["incomplete_arms"] == ["A", "C", "D"]
    assert not any("futile" in v or "point" in v for v in look["look"].values())
    score = {"outcomes": {"A": {"outcome": "KILL"}, "B": {"outcome": "HALTED"}, "C": {"outcome": "FUTILE"},
                          "D": {"outcome": "SURVIVES-history"}}, "selection_section_8_3": {"candidate": "D"}}
    rt.apply_incomplete(score, "r")
    assert score["outcomes"]["B"]["outcome"] == "HALTED" and score["outcomes"]["C"]["outcome"] == "FUTILE"
    assert score["outcomes"]["A"]["outcome"] == score["outcomes"]["D"]["outcome"] == "INCOMPLETE"
    assert score["selection_section_8_3"]["status"].startswith("INCOMPLETE")
    gone = {"outcomes": "[withheld by output guard]"}
    rt.apply_incomplete(gone, "r")
    assert gone["incomplete_arms"] == ["A", "B", "C", "D"]


def test_f4_verify_prev_needs_a_clean_bound_receipt(rt, tmp_path):
    """F4 and G2: the receipt must be COMPLETE, guard-clean, of the same stage and of the same runner sha256."""
    stage = tmp_path / "prev"
    stage.mkdir()
    report = stage / "walk.json"
    runner_sha = "ab" * 32
    report.write_text(json.dumps({"status": "PASS", "runner_sha256": runner_sha}), encoding="utf-8")
    cfg = {"prev": {"controls": {"path": str(report), "sha256": _sha256(report)}}}
    receipt = stage / "receipt.json"
    with pytest.raises(rt.Halt):
        rt.verify_prev(cfg, "controls")  # no receipt
    bound = {"stage": "controls", "walker_sha256": runner_sha}
    upper = {"stage": "controls", "walker_sha256": runner_sha.upper()}
    cases = [(dict(bound, status="COMPLETE", output_guard={"hits_total": 0}), True),
             (dict(upper, status="COMPLETE", output_guard={"hits_total": 0}), True),
             (dict(bound, status="PARTIAL", output_guard={"hits_total": 0}), False),
             (dict(bound, status="HALT", output_guard={"hits_total": 0}), False),
             (dict(bound, status="COMPLETE", output_guard={"hits_total": 1}), False),
             (dict(bound, status="COMPLETE"), False),
             (dict(bound, status="COMPLETE", output_guard={"hits_total": 0}, receipt_guard_hits=2), False),
             (dict(bound, status="COMPLETE", output_guard={"hits_total": 0}, output_guard_flag="x"), False),
             ({"status": "COMPLETE", "output_guard": {"hits_total": 0}}, False),  # unbound (G2)
             (dict(bound, stage="build", status="COMPLETE", output_guard={"hits_total": 0}), False),
             (dict(bound, walker_sha256="cd" * 32, status="COMPLETE", output_guard={"hits_total": 0}), False)]
    for body, ok in cases:
        receipt.write_bytes(b"\xef\xbb\xbf" + json.dumps(body).encode("utf-8"))  # PowerShell 5.1 writes a BOM
        if ok:
            got, where = rt.verify_prev(cfg, "controls")
            assert got["status"] == "PASS" and Path(where) == stage
        else:
            with pytest.raises(rt.Halt):
                rt.verify_prev(cfg, "controls")



def test_f9_score_folds_failures_carry_a_code_only(rt, monkeypatch):
    assert set(rt.SCORE_FOLDS_HALT_CHECKS) == {"SF1", "SF2"}

    def boom_value(*args):
        raise ValueError("brier 0.123456 at " + SEALED_LABEL)

    def boom_halt(*args):
        raise rt.ScoreFoldsHalt("SF2")

    def boom_unlisted(*args):
        raise rt.Halt("label 7 brier 0.5")

    monkeypatch.setattr(rt, "score_folds", boom_value)
    with pytest.raises(rt.ScoreFoldsError) as info:
        rt.run_score_folds(1, 2)
    assert "0.123456" not in str(info.value) and SEALED_LABEL not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__
    monkeypatch.setattr(rt, "score_folds", boom_halt)
    with pytest.raises(rt.ScoreFoldsHalt) as info:
        rt.run_score_folds()
    assert info.value.code == "SF2" and isinstance(info.value, rt.Halt)
    monkeypatch.setattr(rt, "score_folds", boom_unlisted)
    with pytest.raises(rt.ScoreFoldsError) as info:
        rt.run_score_folds()
    assert "0.5" not in str(info.value)
    assert rt.ScoreFoldsHalt("SF7").code == "SF?"



def test_g3_generated_at_is_its_own_markets_pin(rt):
    at = {m: rt.CALIBRATED_WEIGHTS_PINS[f"calibrated_weights_{m}.json"][1] for m in ("atlanta", "austin")}
    assert at["atlanta"] != at["austin"]

    def payload(market, value):
        return {"market": market, "centre": SEALED_LABEL,
                "calibrated_weights": {"metadata": {"generated_at": value}}}

    assert not rt.guard_obj(payload("atlanta", at["atlanta"]), records_file=True)
    assert not rt.guard_obj(payload("austin", at["austin"]), records_file=True)
    assert rt.guard_obj(payload("atlanta", at["austin"]), records_file=True) == SEALED  # another market's pin
    assert rt.guard_obj(payload("toronto", at["atlanta"]), records_file=True) == SEALED  # no mapping
    assert rt.guard_obj(payload(None, at["atlanta"]), records_file=True) == SEALED
    assert rt.guard_obj({"calibrated_weights": {"metadata": {"generated_at": at["atlanta"]}}},
                        records_file=True) == SEALED  # no market at all
    assert rt.records_generated_at_for("seattle") == "2026-06-07T22:15:56"
    assert rt.records_generated_at_for("toronto") is None


def test_item9_b_within_a_and_b_centre_fields(rt):
    centres = _centres()
    b_label, a_only = centres["B"][0], SEALED_LABEL
    assert b_label in centres["A"] and a_only not in centres["B"]
    assert not rt.guard_obj({"B_centre": b_label, "B_train_centre_x": FORWARD_LABEL})
    assert rt.guard_obj({"B_centre": a_only}) == SEALED  # an A-only label in a B field
    assert rt.guard_obj({"B_centres": [b_label, a_only]}) == SEALED
    assert not rt.guard_obj({"A_centre": a_only, "centre": a_only})
    assert rt.guard_obj({"B_note": b_label}) == SEALED  # B_ without "centre" is not a centre field
    bad = dict(centres, B=centres["B"] + ("2026-06-08",))
    try:
        with pytest.raises(rt.Halt):
            rt.set_guard_centres(bad, RECORDS_ROOT)  # B not within A (and the pinned set differs)
        with pytest.raises(rt.Halt):
            rt.set_guard_centres(dict(centres, B=()), RECORDS_ROOT)
    finally:
        assert rt.set_guard_centres(centres, RECORDS_ROOT)["count"] == 24
    assert rt.guard_obj({"B_centre": a_only}) == SEALED
