"""Guards: T018 B1-B6/F1-F5 bounded transport, coverage and failure receipts."""
import base64
import errno
import gzip
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from weather.market.pilot_evidence_account import walk_pages
from weather.market.pilot_evidence_capture import PublicCapture
from weather.market.pilot_evidence_contract import BUILTIN_SPECS, ClockPlan, strict_json
from weather.market.pilot_evidence_coverage import Coverage, event_slug
from weather.market.pilot_evidence_health import BANK_BYTES, HealthFile
from weather.market.pilot_evidence_public import CLOB, PublicHTTP, RateGate, RetryPending
from weather.market.pilot_evidence_schedule import Scheduler, capacity
from weather.market.pilot_evidence_store import CaptureStopped, EvidenceStore, MIB, stamp
from weather.market.pilot_evidence_stream import MarketStream
from weather.market.pilot_evidence_supervisor import WorkerLifeline, supervise
from weather.market.pilot_evidence_transport import BoundedWebSocket, DeadlineSocket, HandshakeError, TransportLimit
from weather.market.pilot_validation_evidence import parser


def make_store(tmp_path, **kwargs):
    kwargs.setdefault("free_space", lambda: 100 * 1024 ** 3)
    store = EvidenceStore(tmp_path / "evidence", memory=lambda: 20 * MIB, **kwargs)
    store.active_at = time.monotonic()
    store.start({"fixture": True})
    return store


def rows(store):
    store.seal()
    return [json.loads(line) for file in sorted(store.root.glob("*.jsonl.gz"))
            for line in gzip.open(file, "rt")]


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class SyntheticSocket:
    def __init__(self, data, clock=None, step=0):
        self.data, self.calls, self.clock, self.step = data, [], clock, step

    def settimeout(self, value):
        pass

    def send(self, raw):
        return len(raw)

    def shutdown(self, how):
        pass

    def close(self):
        pass

    def recv(self, size):
        self.calls.append(size)
        if self.clock:
            self.clock.sleep(self.step)
        value, self.data = self.data[:min(size, 1 if self.step else size)], self.data[min(size, 1 if self.step else size):]
        return value


def book(token="11", cid="0x" + "a" * 64, **overrides):
    return {"event_type": "book", "asset_id": token, "market": cid,
            "timestamp": str(int(time.time() * 1000)),
            "bids": [{"price": ".30", "size": "2"}],
            "asks": [{"price": ".70", "size": "3"}], **overrides}


def seeded_coverage(store):
    specs = {s.id: s for s in BUILTIN_SPECS}
    spec, day = specs["toronto"], date(2026, 1, 2)
    slug = event_slug(spec, day)
    coverage = Coverage(store, [slug])
    band = {"condition_id": "0x" + "a" * 64, "token_ids": ["11", "12"],
            "outcomes": ["Yes", "No"], "market": "toronto", "event_date": day.isoformat(),
            "event_slug": slug, "unit": "C", "question": "synthetic", "gamma_market_id": "1"}
    coverage.discover([band], stamp())
    return coverage, band


@pytest.mark.parametrize("advertised", [MIB + 1, 2 ** 40])
def test_frame_length_is_refused_before_payload_allocation(advertised):
    raw = SyntheticSocket(b"\x81\x7f" + struct.pack("!Q", advertised))
    ws = BoundedWebSocket(DeadlineSocket(raw, lambda: None, time.monotonic() + 2), max_size=MIB)
    with pytest.raises(TransportLimit, match="socket_frame_cap"):
        ws.recv_frame()
    assert raw.calls == [2, 8]


def test_fragment_assembly_limit_is_checked_before_second_payload_read():
    fragment = b"x" * (MIB // 2 + 1)
    encoded = b"\x01\x7f" + struct.pack("!Q", len(fragment)) + fragment
    encoded += b"\x80\x7f" + struct.pack("!Q", len(fragment))
    raw = SyntheticSocket(encoded)
    ws = BoundedWebSocket(DeadlineSocket(raw, lambda: None, time.monotonic() + 2), max_size=MIB)
    assert ws.message(ws.recv_frame()) is None
    before = len(raw.calls)
    with pytest.raises(TransportLimit, match="socket_message_cap"):
        ws.recv_frame()
    assert raw.calls[before:] == [2, 8]


def test_running_stream_shares_fragment_limit_with_socket_receiver(tmp_path):
    store = make_store(tmp_path)
    coverage, _ = seeded_coverage(store)
    fragment = b"x" * (MIB // 2 + 1)
    encoded = b"\x01\x7f" + struct.pack("!Q", len(fragment)) + fragment
    encoded += b"\x80\x7f" + struct.pack("!Q", len(fragment))
    raw = SyntheticSocket(encoded)
    ws = BoundedWebSocket(DeadlineSocket(raw, lambda: None, time.monotonic() + 2), max_size=MIB)
    clock = FakeClock()
    stream = MarketStream(store, RateGate(clock=clock.clock, sleep=clock.sleep),
                          lambda: ["11"], coverage=coverage, connect=lambda: ws)
    stream.run()
    assert stream.decoder is ws
    assert store.reason == "socket_size_cap" and store.counts["ws_frame"] == 1
    assert raw.calls[-2:] == [2, 8]  # No second payload read or allocation.
    store.close("fixture")


def test_shared_cooldown_keeps_health_alive_without_network_requests(tmp_path):
    clock, heartbeats = FakeClock(), []
    store = make_store(tmp_path, clock=clock.clock,
                       health_sink=lambda receipt: heartbeats.append(clock.clock()))
    gate = RateGate(clock=clock.clock, sleep=clock.sleep, check=store.check)
    gate.defer(120)
    gate.wait()
    assert clock.clock() >= 220 and len(heartbeats) >= 100
    assert max(b - a for a, b in zip(heartbeats, heartbeats[1:])) <= 1.21
    assert store.counts["network_starts"] == 0
    store.close("fixture")


def test_truncated_http_body_cannot_validate_even_when_prefix_is_complete_json(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    raw = SyntheticSocket(b"HTTP/1.1 200 OK\r\nContent-Length: 20\r\n\r\n{}")
    monkeypatch.setattr("weather.market.pilot_evidence_transport.tls_socket",
                        lambda *a, **k: DeadlineSocket(raw, lambda: None, time.monotonic() + 2))
    http = PublicHTTP(store, RateGate())
    with pytest.raises(RetryPending):
        http.once(CLOB + "/time")
    partial = [r for r in rows(store) if r["kind"] == "http_incomplete_response"]
    assert len(partial) == 1 and partial[0]["body_complete"] is False
    assert partial[0]["missing_bytes"] == 18 and base64.b64decode(partial[0]["body_base64"]) == b"{}"
    assert not http.pool
    store.close("fixture")


def test_slow_trickle_has_an_absolute_read_deadline():
    clock = FakeClock()
    raw = SyntheticSocket(b"abcdefghij", clock, step=0.2)
    stream = DeadlineSocket(raw, lambda: None, clock.clock() + 0.5, clock=clock.clock)
    with pytest.raises(TimeoutError, match="absolute"):
        stream.exact(10)
    assert len(raw.calls) <= 3


@pytest.mark.parametrize("raw", [b'{"data":[],"data":[1]}', b'{"x":NaN}', b'{"x":1e999}', b"[" * 33 + b"]" * 33])
def test_strict_json_refuses_ambiguous_or_expanding_payload(raw):
    with pytest.raises(ValueError):
        strict_json(raw)


def test_raw_bytes_survive_a_strict_parser_refusal(tmp_path):
    store = make_store(tmp_path)
    raw = b'{"data":[],"data":[1]}'
    assert store.raw("http_response", raw) is None
    retained = next(row for row in rows(store) if row["kind"] == "http_response")
    assert base64.b64decode(retained["body_base64"]) == raw


@pytest.mark.parametrize("stage", ["write", "flush", "fsync", "link", "checksum"])
def test_enospc_at_each_chunk_stage_keeps_a_final_reserved_receipt(tmp_path, monkeypatch, stage):
    store = make_store(tmp_path)
    fault = OSError(errno.ENOSPC, "synthetic full volume")
    if stage == "write":
        monkeypatch.setattr(store.gz, "write", lambda *a: (_ for _ in ()).throw(fault))
    elif stage == "flush":
        monkeypatch.setattr(store.gz, "flush", lambda *a: (_ for _ in ()).throw(fault))
    elif stage == "fsync":
        import os
        real, fd = os.fsync, store.file.fileno()
        def sync(handle):
            if handle == fd:
                raise fault
            return real(handle)
        monkeypatch.setattr(os, "fsync", sync)
    elif stage == "link":
        monkeypatch.setattr("os.link", lambda *a: (_ for _ in ()).throw(fault))
    else:
        real = Path.open
        def opened(path, *args, **kwargs):
            if path.name.endswith(".sha256.json"):
                raise fault
            return real(path, *args, **kwargs)
        monkeypatch.setattr(Path, "open", opened)
    if stage in ("write", "flush"):
        with pytest.raises(CaptureStopped):
            store.write("data", {"test": True})
    else:
        with pytest.raises(CaptureStopped):
            store.seal()
    final = store.close("failed")
    disk = json.loads((store.root / "health.json").read_text())
    assert final["storage_failed"] and disk["final"] and disk["gaps"]["storage_failure"]
    assert store.stop.is_set() and disk["sealed_chunks"] == 0


def test_existing_health_banks_need_no_new_allocation_for_final_enospc(tmp_path, monkeypatch):
    health = HealthFile(tmp_path)
    def no_new_files(*args, **kwargs):
        raise OSError(errno.ENOSPC, "full")
    monkeypatch.setattr(Path, "open", no_new_files)
    health.write({"final": True, "stop_reason": "disk_full"})
    assert all(stream.tell() == BANK_BYTES for stream in health.streams)
    health.close()


def test_failed_primary_health_writes_current_final_to_reserved_fallback(tmp_path, monkeypatch):
    health = HealthFile(tmp_path)
    write = health.write_bank
    def fail_primary(stream, receipt):
        if stream is health.streams[1]:
            raise OSError(errno.ENOSPC, "canonical bank failure")
        return write(stream, receipt)
    monkeypatch.setattr(health, "write_bank", fail_primary)
    health.write({"final": True, "stop_reason": "end_utc", "success": True})
    backup = json.loads((tmp_path / "health.previous.json").read_text())
    assert backup["final"] and not backup["success"] and backup["gaps"]["health_bank_failure"]
    health.close()


def test_free_space_floor_stops_before_the_next_data_write(tmp_path):
    free = [50 * 1024 ** 3]
    store = make_store(tmp_path, free_space=lambda: free[0])
    initial = store.counts.copy()
    free[0] = 40 * 1024 ** 3 - 1
    with pytest.raises(CaptureStopped, match="free_space_floor"):
        store.write("forbidden_after_floor", {})
    result = store.close("failed")
    assert result["stop_reason"] == "free_space_floor"
    assert store.counts["forbidden_after_floor"] == initial["forbidden_after_floor"]


@pytest.mark.parametrize("wall_jump", [-3600, 3600])
def test_clock_steps_fail_closed_without_moving_monotonic_deadline(wall_jump):
    clock, wall = FakeClock(), [1000.0]
    plan = ClockPlan(mono=clock.clock, wall=lambda: wall[0], start=datetime.fromtimestamp(900, timezone.utc),
                     end=datetime.fromtimestamp(1100, timezone.utc))
    assert clock.clock() - plan.start_at == 100  # A late launch retains its missing planned prefix.
    deadline = plan.end_at
    wall[0] += wall_jump
    assert plan.check_clock() == wall_jump and plan.end_at == deadline


@pytest.mark.parametrize("bad", [{"asks": None}, {"market": "0x" + "b" * 64}, {"timestamp": None},
    {"timestamp": "NaN"}, {"timestamp": "1"}, {"bids": [{"price": "2", "size": "1"}]},
    {"asks": [{"price": ".5", "size": "-1"}]}])
def test_skeletal_stale_or_misbound_books_cannot_qualify_coverage(tmp_path, bad):
    store = make_store(tmp_path)
    coverage, _ = seeded_coverage(store)
    assert coverage.book(book(**bad), "11", stamp(), source="rest") is False
    assert coverage.tokens["11"]["baseline_valid_at"] is None
    assert coverage.snapshot()["coverage_ready"] is False


def test_fragmented_book_retains_framing_and_only_recovers_when_complete(tmp_path):
    store = make_store(tmp_path)
    coverage, _ = seeded_coverage(store)
    stream = MarketStream(store, RateGate(), lambda: ["11"], coverage=coverage)
    stream.pending = {"11"}
    stream.disconnected("fixture")
    raw = json.dumps(book()).encode()
    middle = len(raw) // 2
    stream.frame(1, raw[:middle], stamp(), fin=0)
    assert stream.pending == {"11"}
    stream.frame(0, raw[middle:], stamp(), fin=1)
    assert not stream.pending and not stream.gap_open
    frames = [r for r in rows(store) if r["kind"] == "ws_frame"]
    assert [(r["opcode"], r["fin"]) for r in frames] == [(1, 0), (0, 1)]
    assert b"".join(base64.b64decode(r["body_base64"]) for r in frames) == raw


def test_ambiguous_rest_comparison_cannot_close_an_existing_stream_mismatch(tmp_path):
    store = make_store(tmp_path)
    coverage, _ = seeded_coverage(store)
    origin = stamp()
    utc = datetime.fromisoformat(origin["receipt_utc"]) - timedelta(seconds=1)
    def point(index):
        return {"receipt_utc": (utc + timedelta(milliseconds=index)).isoformat(),
                "receipt_monotonic_ns": origin["receipt_monotonic_ns"] - 1_000_000_000 + index * 1_000_000}
    original = book(timestamp=str(int(utc.timestamp() * 1000)))
    changed = {**original, "bids": [{"price": ".4", "size": "2"}]}
    coverage.book(original, "11", point(0), source="stream")
    coverage.book(changed, "11", point(2), source="rest", request_start=point(1))
    assert "stream_rest_mismatch:11" in coverage.intervals
    coverage.book(original, "11", point(4), source="stream")  # Overlaps the request starting at point3.
    coverage.book(changed, "11", point(5), source="rest", request_start=point(3))
    assert "stream_rest_mismatch:11" in coverage.intervals
    assert store.counts["reconciliation_overlaps_stream_update"] == 1
    coverage.book(original, "11", point(7), source="rest", request_start=point(6))
    assert "stream_rest_mismatch:11" not in coverage.intervals
    assert store.gaps["stream_rest_mismatch"] == 1
    store.close("fixture")


def test_arbitrary_event_names_cannot_expand_health_counter_keys(tmp_path):
    store = make_store(tmp_path)
    coverage, _ = seeded_coverage(store)
    stream = MarketStream(store, RateGate(), lambda: ["11"], coverage=coverage)
    stream.frame(1, json.dumps({"event_type": "x" * (MIB // 2)}).encode(), stamp())
    assert store.counts["market_event_other"] == 1
    assert len(json.dumps(store.health())) < BANK_BYTES
    assert store.counts["ws_frame"] == 1  # The unknown raw event still survives.
    store.close("fixture")


def test_gap_starts_at_last_good_receipt_and_pong_is_not_market_liveness(tmp_path):
    store = make_store(tmp_path)
    coverage, _ = seeded_coverage(store)
    good = stamp()
    coverage.book(book(), "11", good, source="rest")
    coverage.book(book(market="bad"), "11", stamp(), source="rest")
    assert coverage.intervals["book_invalid:11"]["from"] == good
    stream = MarketStream(store, RateGate(), lambda: ["11"], coverage=coverage)
    stream.frame(1, b"PONG", stamp())
    for _ in range(10):
        coverage.freshness()
    assert coverage.last_market is None
    assert store.gaps["market_update_silence_uncertain"] == 1


def test_question_revision_continues_but_true_token_reassignment_refuses(tmp_path):
    store = make_store(tmp_path)
    coverage, band = seeded_coverage(store)
    coverage.discover([{**band, "question": "cosmetic correction"}], stamp())
    assert not store.stop.is_set()
    assert any(r["kind"] == "descriptive_metadata_revision" for r in rows(store))
    with pytest.raises(ValueError, match="identity"):
        coverage.discover([{**band, "token_ids": ["91", "92"]}], stamp())


@pytest.mark.parametrize("bands", [40, 44, 45])
@pytest.mark.parametrize("fee_period", [60, None])
@pytest.mark.parametrize("response_seconds", [0.1, 1.0])
@pytest.mark.parametrize("duration", [600, 25200])
def test_full_monday_scheduler_reserves_books_under_feasible_contract(tmp_path, bands, fee_period, response_seconds, duration, request):
    profile = parser().parse_args(["readiness", "--output", str(tmp_path / "readiness")])
    assert profile.fee_seconds == 180
    fee_period = profile.fee_seconds if fee_period is None else fee_period
    clock = FakeClock()
    store = make_store(tmp_path, clock=clock.clock)
    gate = RateGate(profile.max_rest_rps, clock=clock.clock, sleep=clock.sleep)
    scheduler = Scheduler(store, gate, clock=clock.clock, sleep=clock.sleep)
    starts = []
    def call(label):
        gate.start(lambda: starts.append((label, clock.clock())))
        clock.sleep(response_seconds)  # Response latency occurs after the send boundary.
    call("websocket_upgrade")
    call("subscribe")
    scheduler.add("books", profile.rest_book_seconds, lambda: call("books"), immediate=True)
    for index in range(bands):
        scheduler.add(f"reward:{index}", profile.terms_seconds, lambda: call("reward"))
        for field in ("clob-fee", "yes-fee", "no-fee"):
            scheduler.add(f"{field}:{index}", fee_period if field == "clob-fee" else profile.fee_rate_seconds, lambda: call("fee"))
    for index in range(4):
        scheduler.add(f"event:{index}", profile.metadata_seconds, lambda: call("metadata"))
    scheduler.add("time", profile.time_sample_seconds, lambda: call("time"))
    scheduler.add("ping", 9, lambda: call("ping"))
    scheduler.spread()
    # Fresh ten-minute density check and the accepted seven-hour session-day model.
    while clock.clock() < 100 + duration:
        scheduler.service()
    book_times = [at for label, at in starts if label == "books"]
    assert max(b - a for a, b in zip(book_times, book_times[1:])) <= (6.2 if response_seconds == 0.1 else 7.5)
    assert min(b[1] - a[1] for a, b in zip(starts, starts[1:])) >= 0.5 - 1e-8
    if fee_period == 180 and response_seconds == 0.1:
        assert capacity(bands)["feasible"]
        assert store.gaps["rest_cadence_lag"] < 20
    achieved = {"bands": bands, "clob_fee_seconds": fee_period, "response_seconds": response_seconds,
                "modeled_seconds": duration,
                "rest_average_rps": sum(100 <= at < 100 + duration and label not in {"ping", "websocket_upgrade", "subscribe"} for label, at in starts) / duration,
                "book_stats": scheduler.snapshot(), "starts": len(starts),
                "average_starts_per_second": sum(100 <= at < 100 + duration for _, at in starts) / duration,
                "cadence_gap_starts": store.gaps["rest_cadence_lag"], "flags": dict(store.gaps),
                "capacity": capacity(bands, fees=fee_period)}
    for label in ("reward:", "clob-fee:", "yes-fee:", "no-fee:"):
        intervals = [value for key, job in scheduler.jobs.items() if key.startswith(label) for value in job.intervals]
        achieved[label] = {"mean_interval_seconds": sum(intervals) / len(intervals) if intervals else None,
                          "max_interval_seconds": max(intervals) if intervals else None}
    request.node.user_properties.append(("monday_projection", json.dumps(achieved)))


def test_concurrent_slow_journal_and_handshake_cannot_compress_starts(tmp_path, monkeypatch):
    clock, entered, release = FakeClock(), threading.Event(), threading.Event()
    store = make_store(tmp_path)
    gate = RateGate(clock=clock.clock, sleep=clock.sleep)
    write, starts = store.write, []
    def journal(kind, payload, **kwargs):
        if kind == "http_request":
            entered.set()
            assert release.wait(2)
        return write(kind, payload, **kwargs)
    monkeypatch.setattr(store, "write", journal)
    def http(*args):
        starts.append(("rest", clock.clock()))
        return 200, {}, b"1"
    thread = threading.Thread(target=lambda: PublicHTTP(store, gate, request=http).read(CLOB + "/time"))
    thread.start()
    assert entered.wait(2)
    gate.start(lambda: starts.append(("handshake", clock.clock())))
    release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert starts == [("handshake", 100), ("rest", 100.5)]


def stalled_dns_worker(args, channel, cancel):
    lifeline = WorkerLifeline(args.output, channel, cancel)
    lifeline.publish({"final": False, "counts": {}, "gaps": {}, "operations": {
        "dns": {"deadline_monotonic": time.monotonic() + 0.3}}})
    def blocked(*args, **kwargs):
        time.sleep(30)
    socket.getaddrinfo = blocked
    socket.create_connection(("clob.polymarket.com", 443), timeout=0.1)


def test_overall_watchdog_ends_real_worker_stuck_in_dns(tmp_path):
    args = SimpleNamespace(output=tmp_path / "supervised", min_free_gib=40, max_rss_mib=256)
    began = time.monotonic()
    code, health = supervise(args, stalled_dns_worker, grace_seconds=0.2,
                            free_space=lambda: 100 * 1024 ** 3, memory_reader=lambda *a: (20 * MIB, 20 * MIB))
    assert time.monotonic() - began < 5
    assert code == 1 and health["worker_exited"] and health["forced_worker_exit"]
    assert health["stop_reason"] == "transport_watchdog" and health["final"]


def test_account_empty_terminal_cursor_is_kept_and_invalid_rows_refuse(tmp_path):
    store = make_store(tmp_path)
    class HTTP:
        def read(self, *args, **kwargs):
            return {"data": [], "pagination": {"next_cursor": "", "has_more": False}}
    walk_pages(HTTP(), store, "/v2/activity", {}, label="activity", max_pages=1)
    complete = next(r for r in rows(store) if r["kind"] == "account_walk_complete")
    assert complete["terminal_cursor"] == "" and complete["cashflow_rows_validated"] is False
    HTTP.read = lambda *a, **k: {"data": [None], "pagination": {"next_cursor": None, "has_more": False}}
    with pytest.raises(ValueError, match="row shape"):
        walk_pages(HTTP(), store, "/v2/activity", {}, label="bad", max_pages=1)


def test_ambient_registry_override_cannot_open_a_file_on_import(tmp_path):
    code = """
import os
os.environ['WEATHER_MARKET_REGISTRY'] = 'C:/t/codex/T017/DO-NOT-READ.json'
import sys
opened=[]
def audit(event,args):
    if event=='open' and 'DO-NOT-READ' in str(args[0]):
        opened.append(args[0])
        raise RuntimeError('ambient registry read')
sys.addaudithook(audit)
import weather.market.pilot_validation_evidence as cli
assert 'weather.market.market_registry' not in sys.modules
assert not opened
assert len(cli.BUILTIN_SPECS) >= 2
"""
    result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
