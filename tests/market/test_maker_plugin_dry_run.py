"""110h: synthetic sealed-writer layouts only; no production or venue reads."""
import argparse
import builtins
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from weather.market.maker_evidence_store import EvidenceStore
from weather.market.maker_plugin_capture import Reader, Segment, encoded, sealed_segments
from weather.market.maker_plugin_runner import main, run
from tests.market.test_maker_plugin import NOW as BASE_NOW, bulletin, fixture, served_inputs

NOW = BASE_NOW.replace(minute=20)  # Outside the station's scheduled-print pull window.


def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(encoded(r) + b"\n" for r in rows))


def csv_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def layout(tmp_path, *, lead=1, minutes=1, compressed=False):
    root = tmp_path / "inputs"
    _, rows, spec, target, discovery, books = fixture(lead=lead, now=NOW)
    folder = root / "snapshots" / rows[0]["event_slug"]
    csv_rows(folder / "snapshots_long.csv", rows)
    raw = bulletin(spec, target)
    payload = encoded(raw)
    key = hashlib.sha256(payload).hexdigest()
    path = folder / "forecast_payloads" / "sha256" / key[:2] / (key + ".json")
    path.parent.mkdir(parents=True)
    path.write_bytes(payload + b"\n")
    explanation, lineage = served_inputs(rows)
    manifest = dict(lineage, source="nbm_probabilistic_tmax", payload_hash=key)
    jsonl(folder / "forecast_payloads.jsonl", [manifest])
    jsonl(folder / "snapshot_explanations.jsonl", [explanation])
    now = NOW
    store = EvidenceStore(root / "maker_evidence", clock=lambda: now)
    book_payload = json.loads(books["body_utf8"])
    for book in book_payload:
        book["bids"] = [{"price": ".49", "size": "75"}]
        book["asks"] = [{"price": ".51", "size": "75"}]
    for index in range(minutes):
        now = NOW.replace(minute=20 + index)
        store.record("discovery", discovery["body_utf8"].encode(), metadata={"http_status": 200},
                     stored_body=discovery["body_utf8"].encode(), change_key="discovery:fixture")
        for row in rows:
            reward = {"data": [{"condition_id": row["condition_id"], "rewards_min_size": 20,
                       "rewards_max_spread": 5, "rewards_config": [{"rate_per_day": 100,
                       "start_date": NOW.date().isoformat(), "end_date": target.isoformat()}]}]}
            store.record("rewards", encoded(reward), metadata={"http_status": 200},
                         change_key="reward:" + row["condition_id"])
        store.record("books", encoded(book_payload), metadata={"http_status": 200})
    segment = store.folder
    store.seal()
    if compressed:
        for path in list(segment.iterdir()):
            path.with_name(path.name + ".gz").write_bytes(gzip.compress(path.read_bytes()))
            path.unlink()
    args = argparse.Namespace(date=NOW.date().isoformat(), data_root=root, output=tmp_path / "output",
                              markets=["nyc"], max_seconds=60, max_output_bytes=200000000,
                              max_input_bytes=1024**3, hypothetical_hazard_per_minute=None)
    return args, folder, segment


def report(args):
    return json.loads((args.output / "report.json").read_bytes())


def test_real_writer_shards_references_and_gzip(tmp_path):
    args, _, _ = layout(tmp_path, minutes=2, compressed=True)
    summary = run(args)
    result = report(args)
    assert summary["status"] == "COMPLETE"
    assert summary["records_written"] == 2
    assert summary["leg_counts"] == {"0": 6, "1": 0, "2": 0}
    assert summary["decision_reasons"] == {"MISSING_CONSERVATIVE_FILL_BOUND": 6}
    for record in result["records"]:
        assert record["source_coverage"]["bulletins"]["point_in_time_rows"] == 1
        assert record["source_coverage"]["snapshots"]["point_in_time_rows"] == 3
        assert record["probability_mass"]["complete"]
        assert record["probability_mass"]["sum_available"] == pytest.approx(1)
        assert all(o["joins"]["rewards"] and o["joins"]["book"] for o in record["outcomes"])
        assert all(o["settlement"]["reason"] == "settlement_not_recorded_or_event_open" for o in record["outcomes"])
    assert summary["output_bytes"] == sum(p.stat().st_size for p in args.output.iterdir())
    assert summary == result["summary"]


def test_hypothetical_control_can_quote_both_legs(tmp_path):
    args, folder, _ = layout(tmp_path)
    (folder / "forecast_payloads.jsonl").unlink()
    args.hypothetical_hazard_per_minute = .001
    summary = run(args)
    assert summary["leg_counts"] == {"0": 0, "1": 0, "2": 3}
    assert all(o["decision"]["profile"] == "informed-v0" for o in report(args)["records"][0]["outcomes"])


def test_no_input_writes_no_network_no_open_handles_during_policy(tmp_path, monkeypatch):
    args, _, _ = layout(tmp_path)
    before = {p: p.read_bytes() for p in args.data_root.rglob("*") if p.is_file()}
    handles = []
    def guard(original):
        def guarded(file, mode="r", *a, **kw):
            if any(c in mode for c in "wax+"):
                assert Path(file).absolute().is_relative_to(args.output)
            handle = original(file, mode, *a, **kw)
            if "r" in mode and Path(file).absolute().is_relative_to(args.data_root):
                handles.append(handle)
            return handle
        return guarded
    monkeypatch.setattr(builtins, "open", guard(builtins.open))
    monkeypatch.setattr(io, "open", guard(io.open))
    from weather.market import maker_plugin_runner
    original_decide = maker_plugin_runner.decide
    def closed_handles(inputs):
        assert handles and all(h.closed for h in handles)
        return original_decide(inputs)
    monkeypatch.setattr(maker_plugin_runner, "decide", closed_handles)
    monkeypatch.setattr(socket, "socket", lambda *a, **kw: pytest.fail("network accessed"))
    run(args)
    assert before == {p: p.read_bytes() for p in args.data_root.rglob("*") if p.is_file()}


def test_unsealed_status_and_tmp_are_never_opened(tmp_path, monkeypatch):
    args, _, segment = layout(tmp_path)
    (segment / "manifest.json").unlink()
    forbidden = [args.data_root / "maker_evidence" / "status.json", segment / "manifest.json.tmp"]
    for path in forbidden:
        path.write_text("not JSON")
    original = Reader.read
    def guarded(self, path, *a, **kw):
        assert path not in forbidden and path.name != "books.jsonl"
        return original(self, path, *a, **kw)
    monkeypatch.setattr(Reader, "read", guarded)
    summary = run(args)
    assert summary["status"] == "NO_COVERAGE"
    assert summary["coverage"]["segments.unsealed_skipped"] == 1


@pytest.mark.parametrize("defect", ["hash", "escape", "cycle", "missing_part", "future"])
def test_corrupt_sealed_inputs_fail_closed(tmp_path, defect):
    args, _, segment = layout(tmp_path)
    if defect == "hash":
        with (segment / "books.jsonl").open("ab") as handle:
            handle.write(b" ")
    else:
        path = segment / "books.jsonl"
        row = json.loads(path.read_bytes())
        if defect == "escape":
            row["parts"][1]["file"] = "../../credentials.jsonl"
        elif defect == "cycle":
            row.pop("parts")
            row["payload_ref"] = {"file": "books.jsonl", "offset": 0}
        elif defect == "missing_part":
            (segment / row["parts"][1]["file"]).unlink()
        else:
            row["captured_at_utc"] = "2030-01-11T15:00:00+00:00"
        raw = encoded(row) + b"\n"
        path.write_bytes(raw)
        manifest = json.loads((segment / "manifest.json").read_bytes())
        manifest["files"]["books.jsonl"].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        (segment / "manifest.json").write_bytes(encoded(manifest))
    summary = run(args)
    assert summary["coverage"]["segments.rejected"] == 1
    assert not report(args)["records"]


def test_missing_band_metadata_and_partial_mass_are_explicit(tmp_path):
    args, folder, _ = layout(tmp_path)
    (folder / "snapshots_long.csv").unlink()
    summary = run(args)
    assert summary["mass_coverage"] == {"partial": 1}
    assert summary["coverage"]["decisions.not_evaluable"] == 3
    assert summary["unavailable"]["descriptor:missing_captured_band_metadata"] == 3


def test_t0_missing_calibration_is_unavailable(tmp_path):
    args, folder, _ = layout(tmp_path, lead=0)
    path = folder / "forecast_payloads.jsonl"
    row = json.loads(path.read_bytes())
    row.pop("release_calibration_method")
    jsonl(path, [row])
    summary = run(args)
    assert summary["unavailable"]["fair_value:served_release_calibration_unavailable"] == 3
    assert summary["decision_reasons"] == {"HORIZON_NOT_ELIGIBLE": 3}


@pytest.mark.parametrize("cap", ["input", "output", "time"])
def test_caps_leave_valid_bounded_json_and_markdown(tmp_path, cap):
    args, _, _ = layout(tmp_path, minutes=10)
    kw = {}
    if cap == "input":
        args.max_input_bytes = 1
    elif cap == "output":
        args.max_output_bytes = 65536
    else:
        ticks = iter(range(100000))
        kw["clock"] = lambda: next(ticks)
        args.max_seconds = 5
    summary = run(args, **kw)
    assert summary["status"] == "PARTIAL"
    assert cap in summary["stop_reason"]
    assert report(args)["summary"] == summary
    assert summary["output_bytes"] == sum(p.stat().st_size for p in args.output.iterdir())
    assert summary["output_bytes"] <= args.max_output_bytes
    assert summary["input_bytes_read"] <= args.max_input_bytes


def test_cli_and_output_reuse(tmp_path):
    args, _, _ = layout(tmp_path)
    command = [sys.executable, "-B", "-m", "weather.market.maker_plugin.dry_run",
               "--date", args.date, "--data-root", str(args.data_root), "--output", str(args.output),
               "--markets", "nyc", "--max-seconds", "60"]
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    process = subprocess.run(command, capture_output=True, text=True, timeout=30, env=env)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["status"] == "COMPLETE"
    with pytest.raises(ValueError, match="output_must_be"):
        run(args)
    args.output = args.data_root / "snapshots" / "output"
    with pytest.raises(ValueError, match="output_overlaps"):
        run(args)


def test_market_filter(tmp_path):
    args, _, _ = layout(tmp_path)
    args.markets = ["toronto"]
    assert run(args)["status"] == "NO_COVERAGE"


def test_corrupt_nbp_cannot_silently_become_fallback_or_empty_clock(tmp_path):
    args, folder, _ = layout(tmp_path)
    path = next((folder / "forecast_payloads").rglob("*.json"))
    path.write_bytes(b"corrupt")
    summary = run(args)
    assert summary["unavailable"]["fair_value:corrupt_supporting_input"] == 3
    assert summary["unavailable"]["clock:corrupt_clock_input"] == 3
    assert summary["coverage"]["decisions.not_evaluable"] == 3


def test_future_nbp_and_snapshot_rows_do_not_leak(tmp_path):
    args, folder, _ = layout(tmp_path)
    path = folder / "forecast_payloads.jsonl"
    row = json.loads(path.read_bytes())
    row["captured_at_utc"] = "2030-01-10T17:00:00+00:00"
    jsonl(path, [row])
    summary = run(args)
    assert summary["unavailable"]["fair_value:missing_point_in_time_forecast"] == 3


def test_future_corrupt_bulletin_does_not_change_earlier_decisions(tmp_path):
    args, folder, _ = layout(tmp_path)
    future = {"source": "nbm_probabilistic_tmax", "payload_hash": "f" * 64,
              "captured_at_utc": "2030-01-10T17:00:00+00:00"}
    path = folder / "forecast_payloads.jsonl"
    present = json.loads(path.read_bytes())
    jsonl(path, [present, future])  # Future referenced payload is deliberately absent.
    summary = run(args)
    assert summary["leg_counts"] == {"0": 3, "1": 0, "2": 0}
    assert summary["decision_reasons"] == {"MISSING_CONSERVATIVE_FILL_BOUND": 3}
    assert summary["mass_coverage"] == {"complete_unit_mass": 1}


def test_book_age_is_not_replaced_with_decision_time(tmp_path):
    args, _, segment = layout(tmp_path)
    reader = Reader(args.data_root, 60, 1000000)
    _, folder, manifest = sealed_segments(reader, args.date)[0]
    captures = Segment(reader, folder, manifest).captures()
    from weather.market.maker_plugin_runner import captured_book
    from weather.market.maker_plugin.universe import WeatherUniverse
    from datetime import timedelta
    _, rows, _, _, _, _ = fixture(now=NOW)
    universe = WeatherUniverse(discovery=[r for r in captures if r["kind"] == "discovery"],
        books=[r for r in captures if r["kind"] == "books"], band_rows=rows)
    descriptor = universe.discover(NOW, 2).markets[0]
    assert captured_book(captures, descriptor, NOW + timedelta(minutes=1)).as_of_utc == NOW
