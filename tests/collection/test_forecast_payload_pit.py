"""FC-11 served-payload PIT extractor on synthetic event folders.

Guards: DATA_LAYER_V2_PLAN FC-11 / S0b (PIT row counts match manifest counts per day;
embargo dates never opened; run_init never invented; read-only inputs).
"""
from __future__ import annotations

import gzip
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from weather.collection import forecast_payload_pit as fc11


MAX = date(2026, 9, 29)


def _blob(event_dir: Path, payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    path = event_dir / "forecast_payloads" / "sha256" / digest[:2] / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw + b"\n")  # the store's durability newline is not hashed
    return digest


def _row(source, digest, fetched_at, captured, target, *, scope="market_local", ref=True):
    return {
        "source": source,
        "target_date": target,
        "payload_hash": digest,
        "payload_ref": f"sha256/{digest[:2]}/{digest}.json" if ref else "",
        "payload_storage_scope": scope,
        "fetched_at": fetched_at,
        "captured_at_utc": captured,
        "cache_status": "live",
    }


def _open_meteo(fields, times=("2026-08-10T00:00", "2026-08-10T01:00")):
    return {
        "timezone": "America/Los_Angeles",
        "utc_offset_seconds": -25200,
        "hourly": {"time": list(times), **fields},
        "hourly_units": {key: "°F" for key in fields},
    }


def _write_manifest(event_dir: Path, rows, *, garbage_line=False):
    event_dir.mkdir(parents=True, exist_ok=True)
    with (event_dir / "forecast_payloads.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
        if garbage_line:
            handle.write("{not json\n")


@pytest.fixture()
def snapshots(tmp_path: Path) -> Path:
    root = tmp_path / "snapshots"
    sf = root / "highest-temperature-in-san-francisco-on-august-10-2026"
    sf.mkdir(parents=True)
    best = _blob(sf, _open_meteo({
        "temperature_2m": [60.1, 59.0],
        "cloud_cover": [10, None],
    }))
    models = _blob(sf, _open_meteo({
        "temperature_2m_ecmwf_ifs025": [58.0, 57.5],
        "temperature_2m_ecmwf_aifs025": [None, None],
    }))
    ens = _blob(sf, _open_meteo({
        "temperature_2m": [61.0, 60.0],
        "temperature_2m_member01": [62.0, 61.0],
        "temperature_2m_member02": [63.0, 62.0],
    }))
    hourly = _blob(sf, {"properties": {
        "updateTime": "2026-08-10T11:34:26+00:00",
        "periods": [{
            "startTime": "2026-08-10T05:00:00-07:00",
            "temperature": 61,
            "temperatureUnit": "F",
            "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent", "value": 5},
            "dewpoint": {"unitCode": "wmoUnit:degC", "value": 12.2},
            "relativeHumidity": {"unitCode": "wmoUnit:percent", "value": 80},
            "windSpeed": "5 mph",
        }],
    }})
    grid = _blob(sf, {"properties": {
        "updateTime": "2026-08-10T11:34:26+00:00",
        "temperature": {"uom": "wmoUnit:degC", "values": [
            {"validTime": "2026-08-10T12:00:00+00:00/PT3H", "value": 16.1},
            {"validTime": "2026-08-10T15:00:00+00:00/PT1H", "value": None},
        ]},
        "gridId": "MTR",
    }})
    tampered = _blob(sf, _open_meteo({"temperature_2m": [1.0, 2.0]}))
    blob_path = sf / "forecast_payloads" / "sha256" / tampered[:2] / f"{tampered}.json"
    blob_path.write_bytes(blob_path.read_bytes().replace(b"1.0", b"9.0"))
    rows = [
        _row("open_meteo", best, "2026-08-10T01:00:05-07:00", "2026-08-10T08:00:40+00:00", "2026-08-10"),
        # fresh_cache reuse of the same fetch, captured earlier in another copy
        _row("open_meteo", best, "2026-08-10T01:00:05-07:00", "2026-08-10T08:00:20+00:00", "2026-08-10"),
        _row("open_meteo_global_models", models, "2026-08-10T01:00:06-07:00", "2026-08-10T08:00:40+00:00", "2026-08-10"),
        _row("global_ensemble", ens, "2026-08-10T01:00:07-07:00", "2026-08-10T08:00:40+00:00", "2026-08-10"),
        _row("nws_hourly", hourly, "2026-08-10T01:00:08-07:00", "2026-08-10T08:00:40+00:00", "2026-08-10"),
        _row("nws_grid", grid, "2026-08-10T01:00:09-07:00", "2026-08-10T08:00:40+00:00", "2026-08-10"),
        _row("nbm_probabilistic_tmax", "ab" * 32, "2026-08-10T08:00:00+00:00", "2026-08-10T08:00:40+00:00",
             "2026-08-10", scope="shared_market_invariant"),
        _row("open_meteo", "cd" * 32, "2026-08-10T02:00:00-07:00", "2026-08-10T09:00:40+00:00", "2026-08-10"),
        _row("open_meteo", tampered, "2026-08-10T03:00:00-07:00", "2026-08-10T10:00:40+00:00", "2026-08-10"),
    ]
    _write_manifest(sf, rows, garbage_line=True)

    late = root / "highest-temperature-in-nyc-on-september-29-2026"
    late.mkdir(parents=True)
    late_blob = _blob(late, _open_meteo({"temperature_2m": [70.0, 71.0]}))
    _write_manifest(late, [_row("open_meteo", late_blob, "2026-09-29T01:00:00-04:00",
                                "2026-09-29T05:00:10+00:00", "2026-09-29")])

    embargoed = root / "highest-temperature-in-nyc-on-october-1-2026"
    embargoed.mkdir(parents=True)
    (embargoed / "forecast_payloads.jsonl").write_text("SHOULD NEVER BE READ\n", encoding="utf-8")
    (root / "not-an-event").mkdir()
    return root


def _mismatch_receipt(out: Path, day: str) -> dict:
    assert not (out / "receipts" / f"{day}.json").exists()  # a mismatch never seals the day
    (path,) = (out / "receipts").glob(f"{day}.mismatch-*.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _load(path: Path) -> list[dict]:
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq

        return pq.read_table(str(path)).to_pylist()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


@pytest.mark.parametrize("fmt", ["jsonl_gz", "parquet"])
def test_day_receipt_matches_manifest_and_readback(snapshots, tmp_path, fmt):
    if fmt == "parquet":
        pytest.importorskip("pyarrow")
    receipt = fc11.run([snapshots], tmp_path / "out", max_date=MAX, fmt=fmt)
    assert receipt["days_extracted"] == 2
    # 08-10 has one missing and one tampered blob, so it cannot pass.
    assert receipt["all_match"] is False
    assert [(row["target_date"], row["match"]) for row in receipt["days"]] == [
        ("2026-09-29", True), ("2026-08-10", False)]
    assert receipt["event_skips"] == {"embargoed_event": 1, "unparsed_event_name": 1}

    day = _mismatch_receipt(tmp_path / "out", "2026-08-10")
    assert day["manifest_rows"] == 10
    disp = day["dispositions"]
    assert disp["unparseable_row"] == 1
    assert disp["unsupported_source:nbm_probabilistic_tmax"] == 1
    assert disp["fetch_first_row"] == 7 and disp["fetch_repeat_row"] == 1
    assert disp["extracted_rows"] == 6
    assert disp["missing_blob_rows"] == 1 and disp["hash_mismatch_rows"] == 1
    # best 3 numeric cells, models 2, ensemble 6, nws hourly 5, nws grid 1
    assert day["pit_rows_by_source"] == {
        "global_ensemble": 6, "nws_grid": 1, "nws_hourly": 5,
        "open_meteo": 3, "open_meteo_global_models": 2,
    }
    assert day["pit_rows_expected"] == day["pit_rows_readback"] == 17
    assert day["null_or_non_numeric_cells_skipped"] == 4
    assert {name for name, ok in day["checks"].items() if not ok} == {"no_unreadable_fetch_rows"}
    assert day["match"] is False
    assert "temperature_2m" in day["open_meteo_served_fields_seen"]
    assert "cape" in day["open_meteo_served_fields_missing"]

    rows = _load(Path(day["output"]["path"]))
    assert len(rows) == 17
    assert {row["availability_basis"] for row in rows} == {"live_receipt"}
    best = [row for row in rows if row["source"] == "open_meteo"]
    assert {row["run_init"] for row in best} == {"blend_unresolved"}
    assert {row["model"] for row in best} == {"best_match"}
    assert best[0]["first_seen_at"] == "2026-08-10T08:00:20Z"
    assert {row["fetched_at"] for row in best} == {"2026-08-10T08:00:05Z"}
    first_temp = [row for row in best if row["field"] == "temperature_2m"]
    assert sorted(row["valid_time"] for row in first_temp) == ["2026-08-10T07:00:00Z", "2026-08-10T08:00:00Z"]
    ifs = [row for row in rows if row["source"] == "open_meteo_global_models"]
    assert {(row["model"], row["field"], row["run_init"]) for row in ifs} == {
        ("ecmwf_ifs025", "temperature_2m", None)}
    members = sorted({row["member"] for row in rows if row["source"] == "global_ensemble"})
    assert members == [0, 1, 2]
    nws = [row for row in rows if row["source"] == "nws_hourly"]
    assert {row["run_init"] for row in nws} == {"2026-08-10T11:34:26Z"}
    assert {row["valid_time"] for row in nws} == {"2026-08-10T12:00:00Z"}
    grid = [row for row in rows if row["source"] == "nws_grid"]
    assert [(row["field"], row["valid_period"], row["value"]) for row in grid] == [("temperature", "PT3H", 16.1)]


def test_embargoed_event_manifest_is_never_opened(snapshots, tmp_path, monkeypatch):
    opened = []
    original = fc11.read_manifest_rows

    def spy(event_dir):
        opened.append(Path(event_dir).name)
        return original(event_dir)

    monkeypatch.setattr(fc11, "read_manifest_rows", spy)
    fc11.run([snapshots], tmp_path / "out", max_date=MAX, fmt="jsonl_gz")
    assert opened and not any("october" in name for name in opened)


@pytest.mark.parametrize("max_date", [date(2026, 9, 30), date(2026, 10, 15), date(2026, 10, 20)])
def test_request_reaching_the_embargo_is_refused(snapshots, tmp_path, max_date):
    with pytest.raises(fc11.ExtractionRefused, match="embargo"):
        fc11.run([snapshots], tmp_path / "out", max_date=max_date)
    assert not (tmp_path / "out").exists()


def test_min_and_max_date_bound_the_days(snapshots, tmp_path):
    receipt = fc11.run([snapshots], tmp_path / "out", max_date=date(2026, 9, 28),
                       min_date=date(2026, 8, 10), fmt="jsonl_gz")
    assert [row["target_date"] for row in receipt["days"]] == ["2026-08-10"]
    assert receipt["event_skips"]["out_of_range_event"] == 1


def test_row_whose_target_differs_from_its_event_is_refused_before_blob(tmp_path):
    root = tmp_path / "snapshots"
    event = root / "highest-temperature-in-nyc-on-september-29-2026"
    event.mkdir(parents=True)
    _write_manifest(event, [
        _row("open_meteo", "ef" * 32, "2026-09-29T01:00:00-04:00", "2026-09-29T05:00:00+00:00", "2026-10-01"),
        _row("open_meteo", "ef" * 32, "2026-10-01T01:00:00-04:00", "2026-10-01T05:00:00+00:00", "2026-09-29"),
    ])
    receipt = fc11.run([root], tmp_path / "out", max_date=MAX, fmt="jsonl_gz")
    day = json.loads((tmp_path / "out" / "receipts" / "2026-09-29.json").read_text(encoding="utf-8"))
    assert day["dispositions"] == {"row_date_refused": 2}
    assert day["match"] is True and receipt["all_match"] is True


def test_copies_of_one_event_under_two_roots_do_not_duplicate_rows(snapshots, tmp_path):
    import shutil

    copy = tmp_path / "copy" / "snapshots"
    shutil.copytree(snapshots / "highest-temperature-in-nyc-on-september-29-2026",
                    copy / "highest-temperature-in-nyc-on-september-29-2026")
    fc11.run([snapshots, copy], tmp_path / "out", max_date=MAX, min_date=MAX, fmt="jsonl_gz")
    day = json.loads((tmp_path / "out" / "receipts" / "2026-09-29.json").read_text(encoding="utf-8"))
    assert day["manifest_rows"] == 2 and day["event_dirs"] == 2
    assert day["dispositions"]["fetch_repeat_row"] == 1
    assert day["pit_rows_readback"] == 2 and day["match"] is True


def test_out_dir_inside_inputs_is_refused(snapshots):
    with pytest.raises(fc11.ExtractionRefused, match="read-only input tree"):
        fc11.run([snapshots], snapshots / "fc11", max_date=MAX)


def test_deadline_starts_no_day_and_rerun_skips_finished_days(snapshots, tmp_path):
    past = datetime(2000, 1, 1, tzinfo=timezone.utc)
    receipt = fc11.run([snapshots], tmp_path / "out", max_date=MAX, fmt="jsonl_gz", deadline=past)
    assert receipt["stopped_reason"] == "deadline" and receipt["days_extracted"] == 0
    first = fc11.run([snapshots], tmp_path / "out", max_date=MAX, fmt="jsonl_gz", max_days=1)
    assert [row["target_date"] for row in first["days"]] == ["2026-09-29"]
    second = fc11.run([snapshots], tmp_path / "out", max_date=MAX, fmt="jsonl_gz")
    assert [row["status"] for row in second["days"]] == ["already_extracted", "extracted"]


def test_inputs_are_not_modified(snapshots, tmp_path):
    before = {path: path.read_bytes() for path in snapshots.rglob("*") if path.is_file()}
    fc11.run([snapshots], tmp_path / "out", max_date=MAX, fmt="jsonl_gz")
    after = {path: path.read_bytes() for path in snapshots.rglob("*") if path.is_file()}
    assert before == after


@pytest.mark.parametrize("slug,expected", [
    ("highest-temperature-in-san-francisco-on-august-10-2026", ("san-francisco", date(2026, 8, 10))),
    ("lowest-temperature-in-nyc-on-september-9-2026", ("nyc", date(2026, 9, 9))),
    ("highest-temperature-in-nyc-on-smarch-9-2026", None),
    ("highest-temperature-in-nyc-on-february-30-2026", None),
    ("random", None),
])
def test_parse_event_slug(slug, expected):
    assert fc11.parse_event_slug(slug) == expected


def test_main_returns_2_on_refusal(snapshots, tmp_path, capsys):
    code = fc11.main(["--snapshots-root", str(snapshots), "--out-dir", str(tmp_path / "o"),
                      "--max-date", "2026-10-01"])
    assert code == 2
    assert "embargo" in capsys.readouterr().err


@pytest.mark.parametrize("fmt", ["jsonl_gz", "parquet"])
def test_streamed_output_is_in_table_order_across_write_batches(snapshots, tmp_path, monkeypatch, fmt):
    if fmt == "parquet":
        pytest.importorskip("pyarrow")
    monkeypatch.setattr(fc11, "WRITE_BATCH_ROWS", 2)
    fc11.run([snapshots], tmp_path / "out", max_date=MAX, min_date=date(2026, 8, 10),
             max_days=1, fmt=fmt)
    day = json.loads((tmp_path / "out" / "receipts" / "2026-09-29.json").read_text(encoding="utf-8"))
    assert day["match"] is True
    fc11.run([snapshots], tmp_path / "out", max_date=MAX, fmt=fmt)
    day = _mismatch_receipt(tmp_path / "out", "2026-08-10")
    rows = _load(Path(day["output"]["path"]))
    order = [(r["event_slug"], r["source"], r["fetched_at"], r["model"], r["field"],
              -1 if r["member"] is None else r["member"], r["valid_time"]) for r in rows]
    assert len(rows) == day["pit_rows_readback"] == 17 and order == sorted(order)


def test_max_days_counts_only_new_days_and_resumes(snapshots, tmp_path):
    first = fc11.run([snapshots], tmp_path / "out", max_date=MAX, fmt="jsonl_gz", max_days=1)
    assert first["days_extracted"] == 1 and first["days_remaining"] == 1
    assert first["stopped_reason"] == "max_days"
    second = fc11.run([snapshots], tmp_path / "out", max_date=MAX, fmt="jsonl_gz", max_days=1)
    assert [(row["target_date"], row["status"]) for row in second["days"]] == [
        ("2026-09-29", "already_extracted"), ("2026-08-10", "extracted")]
    # 08-10 cannot match (missing and tampered blobs), so it stays open.
    assert second["days_extracted"] == 1 and second["days_remaining"] == 1 and second["all_match"] is False
    third = fc11.run([snapshots], tmp_path / "out", max_date=MAX, fmt="jsonl_gz", max_days=1)
    assert [(row["target_date"], row["status"]) for row in third["days"]] == [
        ("2026-09-29", "already_extracted"), ("2026-08-10", "extracted")]
    assert third["all_match"] is False


def test_mismatched_day_is_redone_after_fresh_days_and_its_table_set_aside(snapshots, tmp_path):
    out = tmp_path / "out"
    first = fc11.run([snapshots], out, max_date=MAX, min_date=date(2026, 8, 10), max_days=1,
                     fmt="jsonl_gz", now=lambda: datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc))
    assert first["days"][0]["target_date"] == "2026-09-29"
    second = fc11.run([snapshots], out, max_date=MAX, fmt="jsonl_gz", max_days=1,
                      now=lambda: datetime(2026, 10, 16, 8, 1, tzinfo=timezone.utc))
    assert second["days"][-1]["receipt"] == "2026-08-10.mismatch-20261016T080100Z.json"
    # A new fresh day appears; it goes before the redo of the mismatched 08-10.
    late = snapshots / "highest-temperature-in-nyc-on-september-1-2026"
    late.mkdir()
    blob = _blob(late, _open_meteo({"temperature_2m": [70.0, 71.0]}))
    _write_manifest(late, [_row("open_meteo", blob, "2026-09-01T01:00:00-04:00", "2026-09-01T05:00:10+00:00",
                                "2026-09-01")])
    third = fc11.run([snapshots], out, max_date=MAX, fmt="jsonl_gz", max_days=1,
                     now=lambda: datetime(2026, 10, 16, 8, 2, tzinfo=timezone.utc))
    assert [row["target_date"] for row in third["days"] if row["status"] == "extracted"] == ["2026-09-01"]
    fourth = fc11.run([snapshots], out, max_date=MAX, fmt="jsonl_gz", max_days=1,
                      now=lambda: datetime(2026, 10, 16, 8, 3, tzinfo=timezone.utc))
    assert [row["target_date"] for row in fourth["days"] if row["status"] == "extracted"] == ["2026-08-10"]
    redo = json.loads((out / "receipts" / "2026-08-10.mismatch-20261016T080300Z.json").read_text(encoding="utf-8"))
    assert len(redo["earlier_attempt_files_set_aside"]) == 1
    assert len(list((out / "receipts").glob("2026-08-10.mismatch-*.json"))) == 2


def test_interrupted_day_is_set_aside_not_overwritten(snapshots, tmp_path):
    day_dir = tmp_path / "out" / "pit" / "target_date=2026-09-29"
    day_dir.mkdir(parents=True)
    (day_dir / "fc11_served_payload_pit.jsonl.gz.partial").write_bytes(b"half")
    (day_dir / "fc11_served_payload_pit.jsonl.gz").write_bytes(b"no receipt")
    fc11.run([snapshots], tmp_path / "out", max_date=MAX, min_date=MAX, fmt="jsonl_gz")
    day = json.loads((tmp_path / "out" / "receipts" / "2026-09-29.json").read_text(encoding="utf-8"))
    assert day["match"] is True and len(day["earlier_attempt_files_set_aside"]) == 2
    kept = sorted(p.read_bytes() for p in day_dir.glob("*.orphan-*"))
    assert kept == [b"half", b"no receipt"]
    assert not list(day_dir.glob("*.partial"))


@pytest.mark.skipif(fc11.os.name != "nt", reason="Windows share modes")
def test_open_input_lets_writers_rename_and_delete(tmp_path):
    path = tmp_path / "manifest.jsonl"
    path.write_text("x\n", encoding="utf-8")
    with fc11.open_input(path, "r", encoding="utf-8") as handle:
        path.rename(tmp_path / "moved.jsonl")
        (tmp_path / "moved.jsonl").unlink()
        assert handle.read() == "x\n"
    with pytest.raises(ValueError):
        fc11.open_input(tmp_path / "other", "w")
