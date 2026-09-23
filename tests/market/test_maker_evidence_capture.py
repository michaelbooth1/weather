"""Deterministic public-shape tests; no venue or developer data access."""
from datetime import datetime, timezone, timedelta
import base64
import gzip
import json
from pathlib import Path

import pytest

from weather.market.maker_evidence_store import EvidenceStore, WriterLock, disk_band, digest, encoded
from weather.market.maker_evidence_public import (
    PublicReader, unique_rows, reward_record, select_universe, modelled_reward,
)
from weather.market.maker_evidence_capture import load_extras, token_pair, get_books

CID = "0x" + "a" * 64
NOW = datetime(2026, 9, 23, 15, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    return EvidenceStore(tmp_path, clock=lambda: NOW)


def manifests(store):
    return [json.loads(row) for row in (store.folder / "manifest.jsonl").read_text().splitlines()]


def test_exact_duplicate_drops_logs_conflict_refuses():
    duplicate = []
    assert unique_rows([{"id": "1", "x": 2}] * 2, key="id", on_duplicate=duplicate.append) == [{"id": "1", "x": 2}]
    assert duplicate == ["1"]
    with pytest.raises(ValueError, match="conflicting"):
        unique_rows([{"id": "1", "x": 2}, {"id": "1", "x": 3}], key="id")


def test_reward_pagination_duplicate_public_shape(store):
    row = {"condition_id": CID, "rewards_min_size": 20, "rewards_max_spread": 4.5,
           "rewards_config": [{"rate_per_day": 8, "start_date": "2026-09-23", "end_date": "2500-12-31"}]}
    class Reader:
        def __init__(self):
            self.store = store
            self.pages = iter([{"data": [row], "next_cursor": "abc"}, {"data": [row], "next_cursor": "LTE="}])
        def read(self, *args, **kwargs):
            return next(self.pages)
    assert reward_record(Reader(), CID) == row
    assert manifests(store)[0]["kind"] == "duplicate"


def test_reward_bodies_only_change_but_every_response_hashed(store):
    raw = b'{"data":[],"count":0}'
    assert store.record("rewards", raw, change_key="reward:a")
    assert not store.record("rewards", b'{"count":0,"data":[]}', change_key="reward:a")
    assert store.record("rewards", b'{"count":1,"data":[1]}', change_key="reward:a")
    rows = manifests(store)
    assert len(rows) == 3
    assert [r["body_stored"] for r in rows] == [True, False, True]
    assert rows[0]["payload_offset"] == rows[1]["payload_offset"]
    assert rows[0]["response_sha256"] == digest(raw)
    assert rows[1]["response_sha256"] != rows[0]["response_sha256"]
    restarted = EvidenceStore(store.root, clock=lambda: NOW)
    assert not restarted.record("rewards", b'{"data":[1],"count":1}', change_key="reward:a")


def test_hard_daily_cap_survives_restart_and_rolls_at_utc_day(tmp_path):
    now = [NOW]
    store = EvidenceStore(tmp_path, stream_cap=10, clock=lambda: now[0])
    assert store.record("stream", b"123456")
    assert not store.record("stream", b"12345")
    assert store.stream_bytes == 6 and store.stream_capped
    restarted = EvidenceStore(tmp_path, stream_cap=10, clock=lambda: now[0])
    assert restarted.stream_capped
    assert not restarted.record("stream", b"1")
    now[0] += timedelta(days=1)
    assert restarted.record("stream", b"12345")
    assert restarted.stream_bytes == 5


def test_orphan_frame_still_counts_against_cap(store):
    store.record("stream", b"123456")
    with (store.folder / "stream.jsonl").open("ab") as handle:
        handle.write(encoded({"sequence": 2, "body_base64": base64.b64encode(b"78901").decode()}) + b"\n")
    restarted = EvidenceStore(store.root, stream_cap=10, clock=lambda: NOW)
    assert restarted.stream_capped and restarted.stream_bytes == 11


@pytest.mark.parametrize("free,band", [(49.9, "critical"), (50, "red"), (59.99, "red"),
                                        (60, "amber"), (74.99, "amber"), (75, "green")])
def test_storage_brake_boundaries(free, band):
    assert disk_band(free * 1024**3) == band


def test_compress_closed_day_roundtrips_and_keeps_current(tmp_path, monkeypatch):
    monkeypatch.setattr(EvidenceStore, "free_bytes", lambda self: 100 * 1024**3)
    now = [NOW]
    store = EvidenceStore(tmp_path, clock=lambda: now[0])
    store.record("books", b'{"asset_id":"123","bids":[]}')
    old_manifest = (store.folder / "manifest.jsonl").read_bytes()
    old_day = store.folder
    now[0] += timedelta(days=1)
    store.record("books", b"[]")
    store.compress_closed_days()
    assert not (old_day / "manifest.jsonl").exists()
    assert gzip.decompress((old_day / "manifest.jsonl.gz").read_bytes()) == old_manifest
    assert (store.folder / "manifest.jsonl").exists()


def test_single_writer_kernel_lock(tmp_path):
    with WriterLock(tmp_path):
        with pytest.raises(RuntimeError, match="already has a writer"):
            with WriterLock(tmp_path):
                pass
    with WriterLock(tmp_path):
        pass


def test_selection_three_per_day_per_city_top_ten_plus_extras():
    rows = [{"city": city, "day_ahead": day, "condition_id": f"{city}:{day}:{i}",
             "modelled_reward_20": 100 - day * 10 - i} for city in ("la", "nyc") for day in range(3) for i in range(5)]
    selected, shortages = select_universe(rows, extras=[{"condition_id": "extra"}])
    assert len(selected) == 21 and not shortages
    for city in ("la", "nyc"):
        assert [sum(row.get("city") == city and row.get("day_ahead") == day for row in selected) for day in range(3)] == [4, 3, 3]


def test_shortage_is_explicit_not_fabricated():
    rows = [{"city": "la", "day_ahead": 1, "condition_id": "a", "modelled_reward_20": 0}]
    selected, shortages = select_universe(rows)
    assert selected == rows
    assert [row["available"] for row in shortages] == [0, 1, 0]


def test_canonical_modelled_twenty_shares_minimum():
    book = {"bids": [{"price": "0.48", "size": "100"}], "asks": [{"price": "0.52", "size": "100"}], "tick_size": "0.01"}
    reward = {"rewards_min_size": 20, "rewards_max_spread": 4.5,
              "rewards_config": [{"rate_per_day": 8, "start_date": "2026-09-23", "end_date": "2500-12-31"}]}
    assert 0 < modelled_reward(book, reward, "2026-09-23") < 8
    reward["rewards_min_size"] = 100
    assert modelled_reward(book, reward, "2026-09-23") == 0


def test_token_yes_no_order_and_invalid_identity():
    assert token_pair({"outcomes": '["No","Yes"]', "clobTokenIds": '["12","34"]'}) == ["34", "12"]
    with pytest.raises(ValueError):
        token_pair({"outcomes": '["Yes","No"]', "clobTokenIds": '["12","12"]'})


def test_extra_file_atomic_owner_contract(tmp_path):
    path = tmp_path / "extra.json"
    path.write_text(json.dumps({"extra_conditions": [CID, CID]}))
    assert load_extras(path) == [CID]
    path.write_text('{"extra_conditions":["bad"]}')
    with pytest.raises(ValueError):
        load_extras(path)


@pytest.mark.parametrize("url,body", [("https://clob.polymarket.com/order", {}),
                                      ("https://clob.polymarket.com/auth/api-key", None),
                                      ("https://evil.invalid/books", []),
                                      ("http://clob.polymarket.com/books", [])])
def test_public_allowlist_refuses_authenticated_and_mutating_routes(store, url, body):
    reader = PublicReader(store)
    try:
        with pytest.raises(ValueError, match="allowlisted"):
            reader.read(url, body=body)
        assert reader.count == 0
        assert reader.session.trust_env is False
    finally:
        reader.close()


def test_books_require_exact_token_coverage(store):
    class Reader:
        def read(self, *args, **kwargs):
            return [{"asset_id": "wrong"}]
    with pytest.raises(ValueError, match="coverage"):
        get_books(Reader(), ["123"], kind="books")


def test_torn_manifest_refuses_without_rewriting(store):
    path = store.folder / "manifest.jsonl"
    path.write_bytes(b'{"broken":')
    with pytest.raises(json.JSONDecodeError):
        EvidenceStore(store.root, clock=lambda: NOW)
    assert path.read_bytes() == b'{"broken":'


def test_critical_disk_stops_before_network_and_writes_status(tmp_path, monkeypatch):
    from weather.market import maker_evidence_capture as capture
    args = capture.build_parser().parse_args(["--root", str(tmp_path / "capture"), "--duration-seconds", "1"])
    monkeypatch.setattr(capture, "lowest_priority", lambda: None)
    monkeypatch.setattr(EvidenceStore, "free_bytes", lambda self: 49 * 1024**3)
    monkeypatch.setattr(capture, "build_universe", lambda *a, **k: pytest.fail("network after critical disk"))
    assert capture.capture(args) == 2
    status = json.loads((args.root / "status.json").read_text())
    assert status["state"] == "STOPPED_CRITICAL_DISK" and status["http"]["requests"] == 0


def test_dry_run_refuses_existing_root_before_process_or_network(tmp_path):
    from weather.market import maker_evidence_capture as capture
    args = capture.build_parser().parse_args(["--root", str(tmp_path), "--dry-run", "--duration-seconds", "1800"])
    with pytest.raises(ValueError, match="NEW scratch"):
        capture.capture(args)


def test_new_schema_storage_classification():
    from weather.operations.storage_classes import classify_storage_path
    assert classify_storage_path("data/maker_evidence/2026-09-23/stream.jsonl").storage_class == "canonical_evidence"


def test_update_socket_closes_on_daily_cap(tmp_path, monkeypatch):
    from weather.market import maker_evidence_stream as module
    store = EvidenceStore(tmp_path, stream_cap=10, clock=lambda: NOW)
    stream = module.PublicStream(store)
    class Stop:
        def is_set(self):
            return False
        def wait(self, seconds):
            return False
    class Socket:
        def __init__(self):
            self.closed = False
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.closed = True
        def send(self, payload):
            pass
        def recv(self, timeout):
            return b"123456"
    socket = Socket()
    stream.stop_event = Stop()
    monkeypatch.setattr(module, "connect", lambda *a, **k: socket)
    stream._run(("123",))
    assert socket.closed and store.stream_capped and store.stream_bytes == 6
    assert stream.connected == 0


def test_trade_channel_retains_explicit_trade_after_update_cap(store, monkeypatch):
    from weather.market import maker_evidence_stream as module
    store.stream_capped = True
    stream = module.PublicStream(store, trades_only=True)
    raw = encoded({"event_type": "last_trade_price", "asset_id": "123", "market": CID,
                   "price": "0.52", "size": "5", "timestamp": "1790175733000", "side": "BUY"})
    class Socket:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def send(self, payload):
            pass
        def recv(self, timeout):
            stream.stop_event.set()
            return raw
    monkeypatch.setattr(module, "connect", lambda *a, **k: Socket())
    stream._run(("123",))
    assert stream.trades == 1 and store.stream_bytes == 0
    assert any(row["kind"] == "trades" and row["response_sha256"] == digest(raw) for row in manifests(store))


def test_completed_capture_inspection_verifies_payload_and_detects_tamper(store):
    from weather.market.maker_evidence_inspect import inspect_capture
    from weather.market.maker_evidence_store import atomic_json
    store.record("books", b"[]")
    atomic_json(store.root / "status.json", {"started_at_utc": NOW.isoformat(),
                "finished_at_utc": (NOW + timedelta(minutes=30)).isoformat(),
                "cycles": 30, "failed_cycles": 0, "http": {}, "stream": {}, "trades": {}})
    result = inspect_capture(store.root, NOW.date().isoformat())
    assert result["manifest_rows_verified"] == 1 and result["elapsed_seconds"] == 1800
    path = store.folder / "books.jsonl"
    row = json.loads(path.read_bytes())
    row["body_base64"] = base64.b64encode(b"{}").decode()
    path.write_bytes(encoded(row) + b"\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        inspect_capture(store.root, NOW.date().isoformat())


def test_handshake_failure_is_recorded_and_retryable(store, monkeypatch):
    from weather.market import maker_evidence_stream as module
    from websockets.exceptions import InvalidHandshake
    stream = module.PublicStream(store)
    def refuse(*args, **kwargs):
        stream.stop_event.set()
        raise InvalidHandshake("temporary public handshake failure")
    monkeypatch.setattr(module, "connect", refuse)
    stream._run(("123",))
    assert stream.errors == 1
    assert manifests(store)[0]["kind"] == "stream_gap"


def test_public_transient_read_retries_only_once_within_budget(store, monkeypatch):
    import requests
    from weather.market import maker_evidence_public as module
    reader = PublicReader(store)
    calls = []
    def fail(*args, **kwargs):
        calls.append(True)
        raise requests.ConnectionError("public disconnect")
    monkeypatch.setattr(reader, "_read_once", fail)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    try:
        with pytest.raises(requests.ConnectionError):
            reader.read("https://clob.polymarket.com/books", body=[])
        assert len(calls) == 2
    finally:
        reader.close()


def test_closed_day_gzip_does_not_hold_active_writer_lock(tmp_path, monkeypatch):
    import threading
    from weather.market import maker_evidence_store as module
    monkeypatch.setattr(EvidenceStore, "free_bytes", lambda self: 100 * 1024**3)
    now = [NOW]
    store = EvidenceStore(tmp_path, clock=lambda: now[0])
    store.record("books", b"[]")
    now[0] += timedelta(days=1)
    store.record("books", b"[]")
    original_open = module.gzip.open
    acquired = []
    def checking_open(*args, **kwargs):
        def probe():
            success = store.lock.acquire(timeout=.5)
            acquired.append(success)
            if success:
                store.lock.release()
        thread = threading.Thread(target=probe)
        thread.start()
        thread.join(timeout=1)
        return original_open(*args, **kwargs)
    monkeypatch.setattr(module.gzip, "open", checking_open)
    assert store.compress_closed_days()
    assert acquired and all(acquired)


def test_public_capture_imports_cannot_read_env_or_load_order_modules():
    import subprocess
    import sys
    program = '''
import pathlib, sys
def guard(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        if pathlib.Path(str(args[0])).name.lower() == ".env":
            raise AssertionError(".env read attempted")
    if event == "import":
        name = args[0]
        if name.startswith(("dotenv", "eth_account", "polymarket", "keyring", "win32cred",
                            "weather.market.mm_", "weather.market.market_making", "weather.market.order_")):
            raise AssertionError("credential/order module import: " + name)
sys.addaudithook(guard)
from weather.market.maker_evidence_capture import build_parser
build_parser().parse_args(["--help"])
'''
    result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_book_reply_partition_preserves_exact_wire_bytes(store):
    raw = ' [ {"asset_id":"123","bids":[],"note":"snow ☃"},\n{"asset_id":"456", "asks":[]} ]\n'.encode()
    store.record("books", raw)
    row = manifests(store)[0]
    payload = json.loads((store.folder / row["payload_file"]).read_bytes())
    chunks = []
    for part in payload["parts"]:
        if "literal_base64" in part:
            chunks.append(base64.b64decode(part["literal_base64"]))
        else:
            with (store.folder / part["file"]).open("rb") as handle:
                handle.seek(part["offset"])
                chunks.append(base64.b64decode(json.loads(handle.readline())["body_base64"]))
    assert b"".join(chunks) == raw
    assert row["response_sha256"] == digest(raw)
    assert (store.folder / "book-123.jsonl").exists()


def test_discovery_projection_retains_all_selection_fields_and_hashes_original(store):
    from weather.market.maker_evidence_public import discovery_projection
    public = [{"id": "1", "slug": "event", "volume": 100, "markets": [
        {"id": "2", "conditionId": CID, "clobTokenIds": '["123","456"]', "outcomes": '["Yes","No"]',
         "active": True, "closed": False, "enableOrderBook": True, "rewardsMinSize": 20,
         "rewardsMaxSpread": 4.5, "clobRewards": [], "volume": 900, "description": "irrelevant"}]}]
    projection = discovery_projection(public)
    assert "volume" not in projection[0] and "description" not in projection[0]["markets"][0]
    assert projection[0]["markets"][0]["conditionId"] == CID
    raw, body = encoded(public), encoded(projection)
    store.record("discovery", raw, stored_body=body, change_key="discovery:1")
    public[0]["volume"] = 200
    assert not store.record("discovery", encoded(public), stored_body=body, change_key="discovery:1")
    rows = manifests(store)
    assert rows[0]["response_sha256"] == digest(raw)
    assert rows[0]["stored_sha256"] == digest(body)
    assert rows[0]["representation"] == "selection_projection"


def test_partitioned_stream_orphan_counts_against_global_cap(store):
    raw = encoded({"market": CID, "event_type": "price_change"})
    store.record("stream", raw)
    path = store.folder / ("updates-" + CID + ".jsonl")
    with path.open("ab") as handle:
        handle.write(encoded({"sequence": 2, "body_base64": base64.b64encode(raw).decode()}) + b"\n")
    restarted = EvidenceStore(store.root, stream_cap=len(raw) + 1, clock=lambda: NOW)
    assert restarted.stream_capped and restarted.stream_bytes == 2 * len(raw)


def test_inspector_verifies_partitioned_books_and_projection(store):
    from weather.market.maker_evidence_inspect import inspect_capture
    raw = b' [{"asset_id":"123", "bids": []}]\n'
    store.record("books", raw)
    store.record("discovery", b'[{"id":1,"volume":100}]',
                 stored_body=b'[{"id":1}]', change_key="discovery:1")
    status = {"started_at_utc": NOW.isoformat(), "finished_at_utc": (NOW + timedelta(minutes=30)).isoformat(),
              "cycles": 30, "failed_cycles": 0, "http": {}, "stream": {}, "trades": {}}
    (store.root / "status.json").write_bytes(encoded(status))
    result = inspect_capture(store.root, NOW.date().isoformat())
    assert result["manifest_rows_verified"] == 2
    assert result["discovery_projection_responses"] == 1
    assert result["response_bytes_by_kind"]["books"] == len(raw)


def test_only_offline_inspector_is_workstation_heavy_allowlisted():
    script = (Path(__file__).resolve().parents[2] / "scripts/ops/workload_admission.ps1").read_text()
    section = script.split("function Get-WeatherWorkstationOfflineModule", 1)[1].split("function ", 1)[0]
    assert '"weather.market.maker_evidence_inspect"' in section
    assert '"weather.market.maker_evidence_capture"' not in section


@pytest.mark.parametrize("raw", [b"upstream unavailable", b"\xff"])
def test_malformed_book_response_is_preserved_and_hashed(store, raw):
    store.record("books", raw)
    row = manifests(store)[0]
    payload = json.loads((store.folder / row["payload_file"]).read_bytes())
    assert base64.b64decode(payload["body_base64"]) == raw
    assert row["response_sha256"] == digest(raw)
