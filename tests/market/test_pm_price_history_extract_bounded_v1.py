"""tools.research.pm_price_history.extract_bounded_v1: synthetic source trees only."""

from __future__ import annotations

import builtins
import hashlib
import json
import os
from pathlib import Path

import pytest

from tools.research.pm_price_history import extract_bounded_v1 as ex

SHA = ex.sha256_file(Path(ex.__file__))
LATE = ("2026-05-27", "2026-06-01", "2026-09-30", "2026-10-03")


def _daily(src, icao, rows, header="local_date,row_count,max_temp_bucket"):
    d = src / icao / "daily"
    d.mkdir(parents=True, exist_ok=True)
    (d / "daily_summary.csv").write_text(header + "\n" + "".join(r + "\n" for r in rows), encoding="utf-8")


def _hourly(src, icao, year, month, dates):
    d = src / icao / "hourly" / f"year={year}" / f"month={month:02d}"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "observations.jsonl", "a", encoding="utf-8") as h:
        for day in dates:
            h.write(json.dumps({"local_date": day, "local_time": "06:00", "temp_native": 50}) + "\n")
        h.write("\n")


def _run(src, out, kind, *extra):
    return ex.main(["--kind", kind, "--source-root", str(src), "--out-root", str(out), "--expect-sha", SHA,
                    *extra])


def _all_text(root):
    return "".join(p.read_text(encoding="utf-8") for p in root.rglob("*") if p.is_file())


def test_daily_emits_only_in_range_and_records_nothing_later(tmp_path, capsys):
    src = tmp_path / "src"
    _daily(src, "klga", ["2024-12-31,24,40", "2025-01-01,24,41", "2026-05-26,24,80",
                         *(f"{d},24,9{i}" for i, d in enumerate(LATE))])
    _daily(src, "kord", ["2026-02-01,24,30"])
    assert _run(src, tmp_path / "out", "daily") == 0
    printed = capsys.readouterr()
    out = next((tmp_path / "out").glob("extract-daily-*"))
    text = _all_text(out) + printed.out + printed.err
    for d in (*LATE, "2024-12-31"):
        assert d not in text
    assert "90" not in (out / "klga" / "daily_summary.csv").read_text(encoding="utf-8")
    lines = (out / "klga" / "daily_summary.csv").read_text(encoding="utf-8").splitlines()
    assert lines == ["local_date,row_count,max_temp_bucket", "2025-01-01,24,41", "2026-05-26,24,80"]
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["script_sha256"] == SHA and m["last"] == "2026-05-26" and m["emitted_rows_total"] == 3
    assert m["files"]["klga/daily_summary.csv"] == {
        "rows": 2, "first": "2025-01-01", "last": "2026-05-26",
        "sha256": hashlib.sha256((out / "klga" / "daily_summary.csv").read_bytes()).hexdigest()}
    assert not any(k for k in json.dumps(m).lower().split('"') if "skip" in k or "source_rows" in k)
    for line in (out / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, rel = line.split("  ", 1)
        assert hashlib.sha256((out / rel).read_bytes()).hexdigest() == digest
    for p in out.rglob("*"):
        if p.is_file():
            assert not os.access(p, os.W_OK)


@pytest.mark.parametrize("bad", ["", "2026-5-1", "2026-02-30", "26/05/2026", "garbage-row-content"])
def test_unparseable_date_refuses_without_echo(tmp_path, capsys, bad):
    src = tmp_path / "src"
    _daily(src, "klga", ["2026-01-01,24,41", f"{bad},24,77777"])
    assert _run(src, tmp_path / "out", "daily") == 2
    err = capsys.readouterr().err
    assert "77777" not in err and (not bad or bad not in err) and "refused" in err


def test_missing_local_date_column_refuses(tmp_path):
    src = tmp_path / "src"
    _daily(src, "klga", ["2026-01-01,24"], header="date,row_count")
    assert _run(src, tmp_path / "out", "daily") == 2


def test_hourly_never_opens_later_partitions(tmp_path, monkeypatch):
    src = tmp_path / "src"
    _hourly(src, "klga", 2026, 4, ["2026-04-30"])
    _hourly(src, "klga", 2026, 5, ["2026-05-26", "2026-05-27", "2026-05-31"])
    _hourly(src, "klga", 2026, 6, ["2026-06-01"])
    _hourly(src, "klga", 2026, 10, ["2026-10-03"])
    real_open = builtins.open
    opened = []

    def spy(path, *a, **k):
        opened.append(str(path).replace("\\", "/"))
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, "open", spy)
    assert _run(src, tmp_path / "out", "hourly") == 0
    monkeypatch.setattr(builtins, "open", real_open)
    assert not any("month=06" in p or "month=10" in p for p in opened)
    out = next((tmp_path / "out").glob("extract-hourly-*"))
    text = _all_text(out)
    for d in ("2026-05-27", "2026-05-31", "2026-06-01", "2026-10-03"):
        assert d not in text
    may = (out / "klga/hourly/year=2026/month=05/observations.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["local_date"] for x in may] == ["2026-05-26"]
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["files"]["klga/hourly/year=2026/month=05/observations.jsonl"]["last"] == "2026-05-26"
    assert m["emitted_rows_total"] == 2


def test_hourly_bad_line_refuses_without_echo(tmp_path, capsys):
    src = tmp_path / "src"
    _hourly(src, "klga", 2026, 3, ["2026-03-01"])
    p = src / "klga/hourly/year=2026/month=03/observations.jsonl"
    with open(p, "a", encoding="utf-8") as h:
        h.write('{"local_date": "2026-13-45", "temp_native": 88888}\n')
    assert _run(src, tmp_path / "out", "hourly") == 2
    err = capsys.readouterr().err
    assert "88888" not in err and "2026-13-45" not in err


def test_argument_refusals(tmp_path, capsys):
    src = tmp_path / "src"
    _daily(src, "klga", ["2026-01-01,24,41"])
    assert _run(src, tmp_path / "out", "daily", "--last", "2026-05-27") == 2
    assert _run(src, tmp_path / "out", "daily", "--first", "2026-03-01", "--last", "2026-02-01") == 2
    assert _run(src, tmp_path / "out", "daily", "--stations", "../x") == 2
    assert ex.main(["--kind", "daily", "--source-root", str(src), "--out-root", str(tmp_path / "out"),
                    "--expect-sha", "0" * 64]) == 2
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())


def test_existing_output_dir_refuses(tmp_path, monkeypatch):
    src = tmp_path / "src"
    _daily(src, "klga", ["2026-01-01,24,41"])

    class Fixed:
        @staticmethod
        def now(tz=None):
            from datetime import datetime, timezone
            return datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(ex, "datetime", Fixed)
    assert _run(src, tmp_path / "out", "daily") == 0
    assert _run(src, tmp_path / "out", "daily") == 3     # FileExistsError, reported by type only


def test_month_bounds():
    assert ex.month_bounds(2026, 2) == (ex.date(2026, 2, 1), ex.date(2026, 2, 28))
    assert ex.month_bounds(2025, 12) == (ex.date(2025, 12, 1), ex.date(2025, 12, 31))
