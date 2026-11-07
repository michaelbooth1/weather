"""Guards: T018 four-event readiness, shared cooldown and actual worker teardown."""
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from weather.market.pilot_evidence_capture import PublicCapture, readiness_from_capture
from weather.market.pilot_evidence_contract import BUILTIN_SPECS
from weather.market.pilot_evidence_health import HealthFile
from weather.market.pilot_evidence_coverage import Coverage, event_slug
from weather.market.pilot_evidence_public import RateGate, allow_url, SOCKET
from weather.market.pilot_evidence_store import EvidenceStore, MIB, stamp
from weather.market.pilot_evidence_stream import MarketStream
from weather.market.pilot_evidence_supervisor import WorkerLifeline, supervise, validate_output
from weather.market.pilot_evidence_transport import DeadlineSocket, HandshakeError, http_exchange, socket_exchange, TransportLimit
from weather.market.pilot_validation_evidence import main
from tests.market.test_pilot_evidence_resilience import FakeClock, SyntheticSocket, book, make_store


def fixture_capture(tmp_path, *, missing_event=None, missing_token=None):
    store = make_store(tmp_path)
    args = SimpleNamespace(market=["denver", "toronto"], event_date=[date(2026, 1, 2), date(2026, 1, 3)],
        rest_book_seconds=5, terms_seconds=60, fee_seconds=180, fee_rate_seconds=180,
        metadata_seconds=180, time_sample_seconds=60, max_age_seconds=30,
        max_mark_delay_seconds=30, max_rest_rps=2)
    events, token_conditions = {}, {}
    specs = {s.id: s for s in BUILTIN_SPECS}
    for index, (market, day) in enumerate((m, d) for m in args.market for d in args.event_date):
        slug, cid = event_slug(specs[market], day), f"0x{index + 1:064x}"
        tokens = [str(100 + 2 * index), str(101 + 2 * index)]
        token_conditions.update({t: cid for t in tokens})
        events[slug] = {"slug": slug, "markets": [{"conditionId": cid,
            "clobTokenIds": json.dumps(tokens), "outcomes": '["Yes","No"]', "question": "synthetic"}]}

    class HTTP:
        gate = RateGate()
        last_body_bytes = 1024

        def once(self, url, **kwargs):
            if "/events/slug/" in url:
                slug = url.rsplit("/", 1)[1]
                if slug == missing_event:
                    raise ValueError("synthetic missing event")
                return events[slug]
            if url.endswith("/books"):
                return [book(row["token_id"], token_conditions[row["token_id"]])
                        for row in kwargs["body"] if row["token_id"] != missing_token]
            raise AssertionError("readiness should not request reward/fee/trading data")
    return PublicCapture(args, store, HTTP()), store, events


def test_output_parent_traversal_cannot_escape_the_task_root(tmp_path):
    with pytest.raises(ValueError, match="normalized absolute"):
        validate_output(tmp_path / "nested" / ".." / "outside")


def test_worker_health_keeps_terminal_space_and_last_valid_recovery_receipt(tmp_path):
    lifeline = WorkerLifeline(tmp_path, SimpleNamespace(send_bytes=lambda raw: None), SimpleNamespace(value=0))
    try:
        with pytest.raises(ValueError, match="reserved capacity"):
            lifeline.publish({"coverage": "x" * (512 * 1024 - 8192)})
        assert lifeline.latest["phase"] == "worker_starting"
    finally:
        lifeline.close()


@pytest.mark.parametrize("command", ["readiness", "account-flow"])
def test_live_interval_refuses_a_second_network_budget(tmp_path, monkeypatch, command):
    class DuringCapture(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
    monkeypatch.setattr("weather.market.pilot_validation_evidence.datetime", DuringCapture)
    output = tmp_path / "refused"
    args = [command, "--output", str(output)]
    if command == "account-flow":
        args += ["--wallet", "0x" + "1" * 40]
    with pytest.raises(SystemExit) as refused:
        main(args)
    assert refused.value.code == 2 and not output.exists()


def test_readiness_proves_all_four_events_and_eight_tokens_with_receipt_times(tmp_path):
    capture, store, _ = fixture_capture(tmp_path)
    assert capture.readiness() == "readiness_complete"
    receipt = store.health()["coverage"]
    assert receipt["expected_events"] == receipt["discovered_events"] == 4
    assert receipt["expected_tokens"] == receipt["baselines_taken"] == receipt["usable_baselines"] == 8
    assert all(r["f0_discovery_agrees"] for r in receipt["events"].values())
    assert all(r["baseline_valid_at"]["receipt_utc"] and r["last_rest"] for r in receipt["tokens"].values())
    assert receipt["coverage_ready"] and receipt["accuracy_qualified"] is False


@pytest.mark.parametrize("fault", [None, "event", "token", "stale", "stale_rest", "stopped", "f0", "checksum"])
def test_readiness_reuses_fresh_checksummed_capture_without_second_rest_budget(tmp_path, fault):
    capture, producer, _ = fixture_capture(tmp_path)
    assert capture.readiness() == "readiness_complete"
    source = {**producer.health(), "phase": "running", "final": False}
    if fault == "event":
        source["coverage"]["events"].pop(next(iter(source["coverage"]["events"])))
    elif fault == "token":
        source["coverage"]["tokens"].pop(next(iter(source["coverage"]["tokens"])))
    elif fault == "stale":
        source["receipt_monotonic_ns"] -= 20_000_000_000
    elif fault == "stale_rest":
        next(iter(source["coverage"]["tokens"].values()))["last_rest"]["receipt_monotonic_ns"] -= 31_000_000_000
    elif fault == "stopped":
        source.update(phase="terminated", final=True)
    elif fault == "f0":
        source["coverage"]["f0_commit"] = "0" * 40
    live = tmp_path / "live"
    live.mkdir()
    reserved = HealthFile(live)
    reserved.write(source)
    reserved.close()
    path = live / "health.json"
    if fault == "checksum":
        path.write_bytes(path.read_bytes().replace(b'"phase":"running"', b'"phase":"stopped"'))
    check = make_store(tmp_path / "check")
    args = SimpleNamespace(**vars(capture.args), capture_health=path)
    if fault == "checksum":
        with pytest.raises(ValueError, match="checksum"):
            readiness_from_capture(args, check)
    else:
        result = readiness_from_capture(args, check)
        assert result == ("readiness_complete" if fault is None else "readiness_incomplete")
    assert check.counts["rest_requests"] == 0
    check.close("fixture")
    producer.close("fixture")


@pytest.mark.parametrize("missing", ["event", "token"])
def test_readiness_refuses_missing_fourth_event_or_one_band_token(tmp_path, missing):
    specs = {s.id: s for s in BUILTIN_SPECS}
    slug = event_slug(specs["toronto"], date(2026, 1, 3))
    capture, store, _ = fixture_capture(tmp_path, missing_event=slug if missing == "event" else None,
                                       missing_token="107" if missing == "token" else None)
    assert capture.readiness() == "readiness_incomplete"
    assert not store.health()["coverage"]["coverage_ready"]


def test_new_token_failed_baseline_cannot_enter_subscription_set(tmp_path):
    capture, store, events = fixture_capture(tmp_path, missing_token="107")
    capture.readiness()
    assert "107" in capture.tokens() and "107" not in capture.coverage.eligible_stream_tokens()
    assert capture.coverage.tokens["107"]["baseline_taken_at"] is None


def test_unexpected_asset_in_rest_batch_never_certifies_any_requested_token(tmp_path):
    capture, store, events = fixture_capture(tmp_path)
    spec = next(s for s in BUILTIN_SPECS if s.id == "toronto")
    capture.discover(spec, date(2026, 1, 2))
    previous = capture.http.once
    capture.http.once = lambda url, **kw: [book("999")] if url.endswith("/books") else previous(url, **kw)
    with pytest.raises(ValueError, match="unexpected"):
        capture.books()
    assert not capture.baselined


@pytest.mark.parametrize("status", [429, 503])
def test_websocket_retry_after_suspends_same_gate_used_by_rest(tmp_path, status):
    store, clock = make_store(tmp_path), FakeClock()
    gate = RateGate(clock=clock.clock, sleep=clock.sleep)
    starts = []
    stream = MarketStream(store, gate, lambda: ["11"], coverage=Coverage(store, ["fixture"]))
    class Ending:
        done = False
        def is_set(self):
            return self.done
        def wait(self, seconds):
            pass
    stream.ending = Ending()
    def connect():
        starts.append(clock.clock())
        if len(starts) == 2:
            stream.ending.done = True
        raise HandshakeError(status, {"Retry-After": "120"}, b"busy")
    stream.connect = connect
    stream.run()
    assert starts == [100, 220]
    assert gate.wait() >= 220.5


@pytest.mark.parametrize("kind", ["rest", "websocket"])
def test_error_headers_defer_shared_gate_before_reading_body(tmp_path, monkeypatch, kind):
    clock = FakeClock()
    store = make_store(tmp_path, clock=clock.clock)
    gate = RateGate(clock=clock.clock, sleep=clock.sleep)
    stream = SimpleNamespace(sendall=lambda raw: None, close=lambda: None)

    class Response:
        status, will_close = 429, True

        def __init__(self, stream):
            pass

        def begin(self):
            pass

        def getheader(self, key, default=None):
            return "120" if key == "Retry-After" else default

        def read(self, size):
            assert gate.next_at >= 220  # Even a slow body starts after cooldown is shared.
            return b"limited"

    monkeypatch.setattr("weather.market.pilot_evidence_transport.tls_socket", lambda *a, **k: stream)
    monkeypatch.setattr("weather.market.pilot_evidence_transport.http.client.HTTPResponse", Response)
    if kind == "rest":
        assert http_exchange("GET", allow_url("GET", "https://clob.polymarket.com/time"),
                             {}, None, gate=gate, store=store)[0] == 429
    else:
        with pytest.raises(HandshakeError):
            socket_exchange(allow_url("WS", SOCKET), gate=gate, store=store)
    assert store.counts["response_header_backoff"] == 1
    store.close("fixture")


def test_handshake_error_body_is_bounded_while_reading(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    wire = b"HTTP/1.1 429 Too Many Requests\r\nContent-Length: 1000000000\r\nRetry-After: 120\r\n\r\n" + b"x" * 16385
    raw = SyntheticSocket(wire)
    stream = DeadlineSocket(raw, store.check, time.monotonic() + 2)
    monkeypatch.setattr("weather.market.pilot_evidence_transport.tls_socket", lambda *a: stream)
    with pytest.raises(HandshakeError) as error:
        socket_exchange(allow_url("WS", SOCKET), gate=RateGate(), store=store)
    assert error.value.status == 429 and error.value.headers["Retry-After"] == "120"
    assert len(error.value.body) == 16384 and error.value.truncated
    assert max(raw.calls) <= 16384


def test_oversized_handshake_header_is_refused_before_large_header_allocation(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    raw = SyntheticSocket(b"HTTP/1.1 429 Busy\r\nX-Long: " + b"x" * 9000 + b"\r\n\r\n")
    stream = DeadlineSocket(raw, store.check, time.monotonic() + 3)
    monkeypatch.setattr("weather.market.pilot_evidence_transport.tls_socket", lambda *a: stream)
    with pytest.raises(TransportLimit, match="line limit"):
        socket_exchange(allow_url("WS", SOCKET), gate=RateGate(), store=store)
    assert len(raw.calls) < 8300


def stopped_worker(args, channel, cancel):
    lifeline = WorkerLifeline(args.output, channel, cancel)
    lifeline.publish({"final": False, "counts": {}, "gaps": {}, "operations": {}})
    while not cancel.value:
        time.sleep(0.05)
    lifeline.publish({"final": True, "stop_reason": "end_utc", "worker_threads_joined": True,
                      "counts": {}, "gaps": {}, "operations": {}, "secondary_errors": {}, "storage_failed": False})
    lifeline.close()
    channel.close()


@pytest.mark.parametrize("trigger", ["deadline", "STOP"])
def test_supervisor_deadline_and_stop_have_actual_bounded_completion(tmp_path, trigger):
    root = tmp_path / "supervised"
    args = SimpleNamespace(output=root, min_free_gib=40, max_rss_mib=256)
    if trigger == "deadline":
        args.end_utc = datetime.now(timezone.utc) + timedelta(seconds=0.5)
    else:
        def stop_file():
            while not root.exists():
                time.sleep(0.01)
            (root / "STOP").touch()
        import threading
        thread = threading.Thread(target=stop_file)
        thread.start()
    began = time.monotonic()
    code, health = supervise(args, stopped_worker, grace_seconds=3,
                            free_space=lambda: 100 * 1024 ** 3, memory_reader=lambda *a: (20 * MIB, 20 * MIB))
    assert time.monotonic() - began < 6
    assert health["worker_exited"] and not health["forced_worker_exit"] and health["final"]
    assert code == (0 if trigger == "deadline" else 1)
    if trigger == "STOP":
        thread.join()


def orphan_resolver_worker(args, channel, cancel):
    lifeline = WorkerLifeline(args.output, channel, cancel)
    lifeline.publish({"final": False, "worker_pid": os.getpid(), "counts": {}, "gaps": {},
                      "operations": {"dns": {"deadline_monotonic": time.monotonic() + 60}}})
    def blocked(*a, **k):
        time.sleep(30)
    socket.getaddrinfo = blocked
    socket.create_connection(("clob.polymarket.com", 443), timeout=0.1)


def test_forceful_sigterm_of_supervisor_does_not_orphan_dns_worker(tmp_path):
    root = tmp_path / "parent-lost"
    code = f"""
from pathlib import Path
from types import SimpleNamespace
from weather.market.pilot_evidence_supervisor import supervise
from tests.market.test_pilot_evidence_readiness import orphan_resolver_worker
if __name__ == '__main__':
    supervise(SimpleNamespace(output=Path({str(root)!r}), min_free_gib=40, max_rss_mib=256), orphan_resolver_worker,
              free_space=lambda: 100 * 1024 ** 3, memory_reader=lambda *a: (20000000, 20000000))
"""
    parent = subprocess.Popen([sys.executable, "-B", "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    receipt = None
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                receipt = json.loads((root / "health.json").read_text())
                if receipt.get("worker_pid") and receipt.get("operations", {}).get("dns"):
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.05)
        assert receipt and receipt.get("worker_pid"), parent.poll()
        parent.terminate()  # TerminateProcess on Windows: no Python signal handler runs.
        parent.wait(3)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            try:
                receipt = json.loads((root / "health.json").read_text())
                if receipt.get("stop_reason") == "supervisor_lost":
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.05)
        assert receipt["final"] and receipt["stop_reason"] == "supervisor_lost"
        assert receipt["exit_requested"] and not receipt["success"]
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(3)
