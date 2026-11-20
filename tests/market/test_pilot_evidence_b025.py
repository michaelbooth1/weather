"""Guards: T036 R1 and B025 terminal congestion, fixed end and isolated launch."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from weather.market.pilot_evidence_stream import MarketStream
from weather.market.pilot_evidence_public import RateGate, allow_url, SOCKET, CLOB, PublicHTTP
from weather.market.pilot_evidence_store import CaptureStopped, EvidenceStore, MIB, stamp
from weather.market.pilot_evidence_contract import ClockPlan
from weather.market.pilot_evidence_supervisor import WorkerLifeline, supervise
from weather.market.pilot_evidence_transport import http_exchange, socket_exchange
from weather.market.pilot_evidence_launch import launch, stop, capture_arguments
from weather.market.pilot_validation_evidence import parser
from tests.market.test_pilot_evidence_resilience import make_store, seeded_coverage, book, rows


def seeded(tmp_path):
    store = make_store(tmp_path)
    coverage, _ = seeded_coverage(store)
    for token in ("11", "12"):
        coverage.book(book(token), token, stamp(), source="rest")
        coverage.book(book(token), token, stamp(), source="stream")
    return store, coverage, MarketStream(store, RateGate(), lambda: ["11", "12"], coverage=coverage)


@pytest.mark.parametrize("kind", ["price_change", "last_trade_price"])
@pytest.mark.parametrize("clock", ["old", "future", "missing", "nonfinite"])
def test_nonbook_stream_timestamp_cannot_leave_clean_coverage(tmp_path, kind, clock):
    store, coverage, stream = seeded(tmp_path)
    assert coverage.snapshot()["coverage_ready"]
    before = coverage.last_market
    row = {"event_type": kind, "market": "0x" + "a" * 64,
           "timestamp": str(int((time.time() + (3600 if clock == "future" else -3600)) * 1000))}
    if clock == "missing":
        row.pop("timestamp")
    elif clock == "nonfinite":
        row["timestamp"] = "NaN"
    if kind == "price_change":
        row["price_changes"] = [{"asset_id": "11", "price": ".3", "size": "9", "side": "BUY"}]
    else:
        row.update(asset_id="11", price=".3", size="9", side="BUY")
    stream.frame(1, json.dumps(row).encode(), stamp())
    code = "stream_source_clock_unreadable" if clock in ("missing", "nonfinite") else "stream_source_delay"
    assert store.gaps[code] == 1 and coverage.last_market == before
    assert not coverage.snapshot()["coverage_ready"]
    assert coverage.stream_books["11"]["book"]["bids"][Decimal(".3")] == 2
    # A fresh print/delta records event timeliness without repairing uncertain full depth.
    row["timestamp"] = str(int(time.time() * 1000))
    stream.frame(1, json.dumps(row).encode(), stamp())
    assert not coverage.snapshot()["coverage_ready"]
    stream.frame(1, json.dumps(book()).encode(), stamp())
    assert coverage.snapshot()["coverage_ready"]
    assert sum(r["kind"] == "ws_frame" for r in rows(store)) == 3
    store.close("fixture")


def test_fresh_delta_has_own_clock_without_certifying_old_full_depth(tmp_path):
    store, coverage, stream = seeded(tmp_path)
    coverage.tokens["11"]["source_age_at_observation"] = 60
    row = {"event_type": "price_change", "market": "0x" + "a" * 64,
           "timestamp": str(int(time.time() * 1000)),
           "price_changes": [{"asset_id": "11", "price": ".3", "size": "9", "side": "BUY"}]}
    stream.frame(1, json.dumps(row).encode(), stamp())
    snapshot = coverage.snapshot()
    assert snapshot["tokens"]["11"]["stream_event_fresh"]
    assert snapshot["tokens"]["11"]["source_age_seconds"] >= 60
    assert not snapshot["tokens"]["11"]["baseline_usable"] and not snapshot["coverage_ready"]
    stream.frame(1, json.dumps(book()).encode(), stamp())
    assert coverage.snapshot()["coverage_ready"]
    store.close("fixture")


@pytest.mark.parametrize("transport", ["rest", "websocket"])
@pytest.mark.parametrize("status,hint", [(429, None), (503, "120"), (200, "")])
def test_first_congestion_header_stops_before_body_and_never_retries(tmp_path, monkeypatch, transport, status, hint):
    store = make_store(tmp_path)
    gate = RateGate(check=store.check)
    closed, sends = [], []
    wire = SimpleNamespace(sendall=lambda raw: sends.append(raw), close=lambda: closed.append(True))
    class Response:
        def __init__(self, stream):
            self.status = status
        def begin(self):
            pass
        def getheader(self, key, default=None):
            return hint if key == "Retry-After" else default
        def read(self, size):
            raise AssertionError("terminal congestion must not wait for a body")
    monkeypatch.setattr("weather.market.pilot_evidence_transport.tls_socket", lambda *a, **k: wire)
    monkeypatch.setattr("weather.market.pilot_evidence_transport.http.client.HTTPResponse", Response)
    endpoint = CLOB + "/time" if transport == "rest" else SOCKET
    with pytest.raises(CaptureStopped, match="venue_congestion"):
        if transport == "rest":
            http_exchange("GET", allow_url("GET", endpoint), {}, None, gate=gate, store=store)
        else:
            socket_exchange(allow_url("WS", endpoint), gate=gate, store=store)
    with pytest.raises(CaptureStopped, match="venue_congestion"):
        gate.start(lambda: sends.append("forbidden retry"))
    assert len(sends) == len(closed) == 1 and gate.halted.is_set()
    gap = next(row for row in rows(store) if row.get("code") == "venue_congestion")
    assert gap["endpoint"] == endpoint and gap["status"] == status
    assert gap["header_received"]["receipt_utc"] and gap["response_headers"]["Retry-After"] == hint
    assert gap["retry_policy"] == "terminal_no_restart" and gap["response_body_unread"]
    final = store.close("venue_congestion")
    assert final["final"] and final["gaps"]["venue_congestion"] == 1


def congestion_worker(args, channel, cancel):
    lifeline = WorkerLifeline(args.output, channel, cancel)
    store = EvidenceStore(args.output, existing_root=True, health_sink=lifeline.publish, cancel=cancel,
                          free_space=lambda: 100 * 1024 ** 3, memory=lambda: 20 * MIB)
    store.start({"fixture": True})
    try:
        PublicHTTP(store, RateGate(check=store.check), request=lambda *a: (429, {}, b"{}")).read(CLOB + "/time")
    except CaptureStopped:
        pass
    receipt = store.close("venue_congestion")
    receipt["worker_threads_joined"] = True
    lifeline.publish(receipt)
    lifeline.close()
    channel.close()


def test_congestion_has_clean_process_exit_and_incomplete_evidence(tmp_path):
    args = SimpleNamespace(output=tmp_path / "congestion", min_free_gib=40, max_rss_mib=256)
    code, final = supervise(args, congestion_worker, free_space=lambda: 100 * 1024 ** 3,
                            memory_reader=lambda *a: (20 * MIB, 20 * MIB))
    assert code == 0 and final["clean_exit"] and final["worker_exited"] and not final["forced_worker_exit"]
    assert not final["success"] and not final["coverage"]["coverage_ready"]
    assert final["stop_reason"] == "venue_congestion" and final["gaps"]["venue_congestion"] == 1


@pytest.mark.parametrize("late_seconds", [0, 3600, 25201])
def test_late_start_never_moves_absolute_end(late_seconds):
    start = datetime(2026, 11, 9, 17, 45, tzinfo=timezone.utc)
    end = datetime(2026, 11, 10, 0, 45, tzinfo=timezone.utc)
    now = start.timestamp() + late_seconds
    plan = ClockPlan(start=start, end=end, mono=lambda: 100, wall=lambda: now)
    assert plan.end_at == 100 + max(0, end.timestamp() - now)
    assert plan.start_at == 100 - late_seconds
    assert plan.anchors()["end_utc"] == "2026-11-10T00:45:00+00:00"


def test_independent_launch_owns_only_evidence_handle_and_one_end(tmp_path):
    root = tmp_path / "launched"
    args = parser().parse_args(["launch", "--expected-tip", "a" * 40, "--market", "toronto", "--event-date", "2026-11-10",
        "--all-bands", "--both-tokens", "--raw-market-stream", "--end-utc", "2026-11-10T00:45:00Z", "--output", str(root)])
    calls = []
    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(pid=12345, wait=lambda *a, **k: pytest.fail("launch must not wait"))
    receipt = launch(args, popen=popen, tip_reader=lambda: "a" * 40)
    command, options = calls[0]
    assert command.count("--end-utc") == 1 and command[command.index("--end-utc") + 1] == "2026-11-10T00:45:00+00:00"
    assert "--start-utc" not in command and "--duration" not in command
    assert receipt["automatic_restart"] is False and receipt["supervisor_pid"] == 12345
    if os.name == "nt":
        assert options["creationflags"] & subprocess.DETACHED_PROCESS
        assert options["creationflags"] & subprocess.CREATE_BREAKAWAY_FROM_JOB
    root.mkdir()  # The actual child supervisor normally creates its own root.
    unrelated = tmp_path / "unrelated-stop"
    assert stop(root)["stop_requested"] and (root / "STOP").exists() and not unrelated.exists()
    with pytest.raises(ValueError, match="new normalized"):
        launch(args, popen=popen, tip_reader=lambda: "a" * 40)


def isolated_worker(args, channel, cancel):
    lifeline = WorkerLifeline(args.output, channel, cancel)
    lifeline.publish({"final": False, "counts": {}, "gaps": {}, "operations": {}})
    (Path(args.output) / "ready").touch()
    if args.mode == "crash":
        lifeline.close()
        raise RuntimeError("synthetic evidence crash")
    while not cancel.value:
        time.sleep(0.02)
    lifeline.publish({"final": True, "stop_reason": "operator_stop_file", "counts": {}, "gaps": {},
                      "worker_threads_joined": True, "secondary_errors": {}, "storage_failed": False})
    lifeline.close()


@pytest.mark.spawns
@pytest.mark.parametrize("mode", ["STOP", "crash", "kill"])
def test_sidecar_stop_crash_and_kill_leave_unrelated_process_running(tmp_path, mode):
    root = tmp_path / "owned"
    code = f"""
from pathlib import Path
from types import SimpleNamespace
from weather.market.pilot_evidence_supervisor import supervise
from tests.market.test_pilot_evidence_b025 import isolated_worker
if __name__ == '__main__':
    supervise(SimpleNamespace(output=Path({str(root)!r}), mode={mode!r}, min_free_gib=40, max_rss_mib=256), isolated_worker,
              free_space=lambda: 100*1024**3, memory_reader=lambda *a: (20000000,20000000))
"""
    unrelated = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(30)"])
    owned = subprocess.Popen([sys.executable, "-B", "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 10
        while not (root / "ready").exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert (root / "ready").exists()
        if mode == "STOP":
            (root / "STOP").touch()
        elif mode == "kill":
            owned.terminate()
        owned.wait(timeout=6)
        assert unrelated.poll() is None
        if mode == "kill":
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                final = json.loads((root / "health.json").read_text())
                if final.get("stop_reason") == "supervisor_lost":
                    break
                time.sleep(.05)
            assert final["stop_reason"] == "supervisor_lost" and final["final"]
    finally:
        if owned.poll() is None:
            owned.kill()
        owned.wait(3)
        unrelated.terminate()
        unrelated.wait(3)
