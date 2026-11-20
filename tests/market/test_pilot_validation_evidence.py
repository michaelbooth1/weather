"""Guards: T017 public-only, bounded raw pilot evidence and cursor completeness."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from weather.market.pilot_evidence_account import account_flow, walk_pages
from weather.market.pilot_evidence_capture import MarketStream, PublicCapture, event_bands
from weather.market.pilot_evidence_public import CLOB, DATA, SOCKET, PublicHTTP, RateGate, allow_url, retry_delay
from weather.market.pilot_evidence_store import CaptureStopped, EvidenceStore, MIB, stamp
from weather.market.pilot_validation_evidence import main, parser
from weather.market.pilot_evidence_contract import BUILTIN_SPECS
from weather.market.pilot_evidence_coverage import Coverage
from datetime import date

TORONTO = next(spec for spec in BUILTIN_SPECS if spec.id == "toronto")


class Clock:
    def __init__(self):
        self.now = 100.0
        self.waits = []

    def clock(self):
        return self.now

    def sleep(self, amount):
        self.waits.append(amount)
        self.now += amount


def store_at(tmp_path, **kwargs):
    kwargs.setdefault("free_space", lambda: 100 * 1024 ** 3)
    store = EvidenceStore(tmp_path / "evidence", memory=lambda: 20 * MIB, **kwargs)
    store.start({"test": True})
    return store


def records(store):
    store.seal()
    return [json.loads(line) for path in sorted(store.root.glob("*.jsonl.gz"))
            for line in gzip.open(path, "rt", encoding="utf-8")]


def test_rate_gate_has_no_burst_and_defers_global_budget():
    clock = Clock()
    gate = RateGate(2, clock=clock.clock, sleep=clock.sleep)
    starts = [gate.wait() for _ in range(8)]
    assert starts == [100 + 0.5 * i for i in range(8)]
    gate.defer(3)
    assert gate.wait() == 106.5
    assert max(clock.waits) <= 0.2


@pytest.mark.parametrize("rps", [0, -1, 2.01, 4])
def test_rate_gate_refuses_unsafe_rate(rps):
    with pytest.raises(ValueError):
        RateGate(rps)


@pytest.mark.parametrize("method,url,params", [
    ("GET", CLOB + "/time", {}), ("POST", CLOB + "/books", {}),
    ("GET", CLOB + "/fee-rate", {"token_id": "12"}),
    ("GET", CLOB + "/clob-markets/0x" + "a" * 64, {}),
    ("GET", DATA + "/v2/activity", {"user": "0x" + "a" * 40, "cursor": "opaque/+="}),
    ("WS", SOCKET, {}),
])
def test_allowlisted_reads(method, url, params):
    assert allow_url(method, url, params).hostname.endswith("polymarket.com")


@pytest.mark.parametrize("method,url,params", [
    ("GET", "http://clob.polymarket.com/time", {}),
    ("GET", "https://clob.polymarket.com.evil.test/time", {}),
    ("GET", "https://user:pass@clob.polymarket.com/time", {}),
    ("GET", CLOB + ":443/time", {}), ("GET", CLOB + "/time?auth=x", {}),
    ("GET", CLOB + "/time#x", {}), ("GET", CLOB + "/%74ime", {}),
    ("GET", CLOB + "/\ntime", {}),
    ("GET", CLOB + "/time", {"auth": "x"}), ("POST", CLOB + "/order", {}),
    ("DELETE", CLOB + "/books", {}), ("GET", DATA + "/v2/activity/../orders", {}),
    ("WS", SOCKET + "/user", {}), ("GET", "https://polymarket.us/time", {}),
])
def test_refuse_non_allowlisted_url_before_network(method, url, params):
    with pytest.raises(ValueError, match="allowlisted"):
        allow_url(method, url, params)


def test_http_429_is_terminal_and_unhinted_5xx_backoff_preserves_bodies(tmp_path):
    clock = Clock()
    store = store_at(tmp_path)
    gate = RateGate(2, clock=clock.clock, sleep=clock.sleep)
    starts = []
    responses = iter([(503, {}, b'{"down":true}'), (200, {}, b'{"ok":true}'),
                      (429, {"Retry-After": "7"}, b'{"busy":true}')])

    def request(*args):
        starts.append(clock.clock())
        return next(responses)

    client = PublicHTTP(store, gate, request=request)
    assert client.read(CLOB + "/time") == {"ok": True}
    with pytest.raises(CaptureStopped, match="venue_congestion"):
        client.read(CLOB + "/time")
    assert starts == [100, 102, 102.5]
    rows = records(store)
    bodies = [base64.b64decode(r["body_base64"]) for r in rows if r["kind"] == "http_response"]
    assert bodies == [b'{"down":true}', b'{"ok":true}', b'{"busy":true}']
    assert store.gaps["http_backoff"] == store.gaps["venue_congestion"] == 1


def test_http_redirect_never_followed(tmp_path):
    store = store_at(tmp_path)
    calls = []
    client = PublicHTTP(store, RateGate(), request=lambda *a: calls.append(a) or (302, {}, b"redirect"))
    with pytest.raises(ValueError):
        client.read(CLOB + "/time")
    assert len(calls) == 1
    assert store.gaps["http_status"] == 1


def test_slow_request_journal_cannot_compress_http_start_spacing(tmp_path, monkeypatch):
    clock = Clock()
    store = store_at(tmp_path)
    gate = RateGate(2, clock=clock.clock, sleep=clock.sleep)
    write, starts = store.write, []

    def slow_first(kind, payload, **kwargs):
        if kind == "http_request" and not starts:
            clock.sleep(1)
        return write(kind, payload, **kwargs)

    monkeypatch.setattr(store, "write", slow_first)

    def request(*args):
        starts.append(clock.clock())
        return 200, {}, b"1"

    http = PublicHTTP(store, gate, request=request)
    http.read(CLOB + "/time")
    http.read(CLOB + "/time")
    assert starts == [101, 101.5]


def test_retry_after_http_date_and_exponential_bound():
    from datetime import datetime, timezone
    assert retry_delay("Fri, 06 Nov 2026 23:01:00 GMT", 1,
                       datetime(2026, 11, 6, 23, tzinfo=timezone.utc)) == 60
    assert retry_delay("invalid", 100) == 300
    assert retry_delay("900", 1) == 900


def test_output_cap_stops_cleanly_with_gap_and_final_receipt(tmp_path):
    store = store_at(tmp_path, max_output_mib=2)
    with pytest.raises(CaptureStopped, match="output_cap"):
        store.write("large", {"body": "a" * (2 * MIB)})
    health = store.close("failed")
    assert health["stop_reason"] == "output_cap"
    assert health["gaps"]["output_cap"] == 1
    assert health["output_bytes"] < 2 * MIB
    assert records(store)[-1]["kind"] == "stop"


def test_rss_cap_stops_and_records_current_peak(tmp_path):
    memory = [10 * MIB]
    store = EvidenceStore(tmp_path / "rss", max_rss_mib=32, memory=lambda: memory[0], free_space=lambda: 100 * 1024 ** 3)
    store.start({})
    memory[0] = 32 * MIB
    with pytest.raises(CaptureStopped, match="rss_cap"):
        store.check()
    assert store.close("failed")["peak_rss_bytes"] == 32 * MIB
    assert store.gaps["rss_cap"] == 1


def test_initial_rss_cap_also_seals_a_final_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr("weather.market.pilot_evidence_supervisor.shutil.disk_usage",
                        lambda *args: SimpleNamespace(free=100 * 1024 ** 3))
    root = tmp_path / "initial-cap"
    assert main(["account-flow", "--wallet", "0x" + "1" * 40,
                 "--max-rss-mib", "0.001", "--output", str(root)]) == 1
    receipt = json.loads((root / "health.json").read_text())
    assert receipt["final"] and receipt["stop_reason"] == "rss_cap"
    assert receipt["counts"].get("rest_requests", 0) == 0


def test_stop_file_is_a_clean_gap_stop(tmp_path):
    store = store_at(tmp_path)
    (store.root / "STOP").touch()
    with pytest.raises(CaptureStopped, match="operator_stop_file"):
        store.check()
    assert store.close("failed")["gaps"] == {"operator_stop_file": 1}


def test_http_response_cap_stops_before_unbounded_record(tmp_path):
    store = store_at(tmp_path)
    client = PublicHTTP(store, RateGate(), request=lambda *a: (200, {}, b"x" * (4 * MIB + 1)))
    with pytest.raises(CaptureStopped, match="http_body_cap"):
        client.read(CLOB + "/time")
    assert store.close("failed")["gaps"]["http_body_cap"] == 1


def test_http_refuses_bad_url_before_request(tmp_path):
    store = store_at(tmp_path)
    calls = []
    client = PublicHTTP(store, RateGate(), request=lambda *a: calls.append(a))
    with pytest.raises(ValueError, match="allowlisted"):
        client.read("https://example.com/time")
    assert not calls and not store.counts["rest_requests"]


def test_chunks_checksum_exact_bytes_and_refuse_root_reuse(tmp_path):
    store = store_at(tmp_path, chunk_bytes=200)
    for _ in range(5):
        store.raw("ws_frame", b'{"timestamp":"1794000000000","asset_id":"12"}')
    health = store.close("test")
    assert health["sealed_chunks"] >= 3
    for receipt_path in store.root.glob("*.sha256.json"):
        receipt = json.loads(receipt_path.read_text())
        raw = (store.root / receipt["file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == receipt["sha256"]
        assert len(raw) == receipt["bytes"]
    frames = [r for r in records(store) if r["kind"] == "ws_frame"]
    assert len(frames) == 5  # Identical-looking observations are never removed.
    assert all(r["receipt_monotonic_ns"] > 0 and r["receipt_utc"] for r in frames)
    clocks = [r for r in records(store) if r["kind"] == "source_clocks"]
    assert clocks[0]["source_timestamps"] == [{"field": "timestamp", "value": "1794000000000"}]
    with pytest.raises(FileExistsError):
        EvidenceStore(store.root)


def test_stream_gap_closes_only_after_all_token_book_frames(tmp_path):
    store = store_at(tmp_path)
    coverage = Coverage(store, ["synthetic"])
    coverage.tokens = {t: {"condition_id": "0x" + "a" * 64, "event": "synthetic",
        "baseline_taken_at": None, "baseline_valid_at": None, "last_rest": None,
        "last_stream": None, "source_age_seconds": None, "baseline_usable": False,
        "rest_observation_fresh": False} for t in ("1", "2")}
    stream = MarketStream(store, RateGate(), lambda: ["1", "2"], coverage=coverage)
    stream.disconnected("test")
    stream.pending = {"1", "2"}
    def full_book(token):
        return json.dumps({"event_type": "book", "asset_id": token, "market": "0x" + "a" * 64,
                           "timestamp": str(int(__import__('time').time() * 1000)), "bids": [], "asks": []}).encode()
    stream.frame(1, full_book("1"), stamp())
    stream.frame(1, b'PONG', stamp())
    assert stream.gap_open
    stream.frame(1, full_book("2"), stamp())
    assert not stream.gap_open
    rows = records(store)
    assert [r["kind"] for r in rows].count("stream_transport_recovered") == 1
    assert len([r for r in rows if r["kind"] == "ws_frame"]) == 3


def test_stream_reconnect_is_journaled_and_bounded(tmp_path):
    store = store_at(tmp_path)
    clock = Clock()
    gate = RateGate(clock=clock.clock, sleep=clock.sleep)
    attempts, waits = [], []
    stream = MarketStream(store, gate, lambda: ["1"], coverage=Coverage(store, ["synthetic"]))

    class Ending:
        done = False

        def is_set(self):
            return self.done

        def wait(self, seconds):
            waits.append(seconds)

    ending = Ending()
    stream.ending = ending

    def connect():
        attempts.append(1)
        if len(attempts) == 2:
            ending.done = True
        raise ConnectionError("offline fixture")

    stream.connect = connect
    stream.run()
    assert len(attempts) == 2
    assert waits == [0.2]
    assert store.gaps["stream_transport_gap"] == 1
    assert any(r["kind"] == "stream_reconnect" for r in records(store))


def band(cid="a", tokens=("11", "12")):
    return {"conditionId": "0x" + cid * 64, "clobTokenIds": json.dumps(tokens),
            "outcomes": '["No","Yes"]', "question": "synthetic band", "closed": False}


def test_discovery_latches_all_bands_and_both_outcomes(tmp_path):
    store = store_at(tmp_path)
    day = date(2026, 1, 2)
    event = {"slug": "highest-temperature-in-toronto-on-january-2-2026", "markets": [band(), band("b", ("21", "22"))]}

    class HTTP:
        gate = RateGate()
        last_body_bytes = 100

        def once(self, url, **kwargs):
            if url.endswith("/books"):
                return [{"asset_id": row["token_id"], "market": "0x" + ("a" if row["token_id"] in ("11", "12") else "b") * 64,
                         "bids": [], "asks": [], "timestamp": str(int(__import__('time').time() * 1000))}
                        for row in kwargs["body"]]
            return event

    capture = PublicCapture(SimpleNamespace(market=["toronto"], event_date=[day], rest_book_seconds=5,
                            terms_seconds=60, metadata_seconds=180, fee_seconds=180, fee_rate_seconds=180,
                            max_rest_rps=2, max_age_seconds=30, max_mark_delay_seconds=30), store, HTTP())
    capture.discover(TORONTO, day)
    capture.books()
    assert capture.tokens() == ["11", "12", "21", "22"]
    assert capture.baselined == set(capture.tokens())
    event["markets"] = [band()]
    capture.discover(TORONTO, day)
    assert capture.tokens() == ["11", "12", "21", "22"]
    assert store.gaps["event_membership_missing"] == 1
    identity = [r for r in records(store) if r["kind"] == "band_identity"]
    assert len(identity) == 2 and all(r["unit"] == "C" for r in identity)
    assert identity[0]["outcomes"] == ["No", "Yes"]


def test_refuse_ambiguous_identity():
    event = {"slug": "highest-temperature-in-toronto-on-january-2-2026", "markets": [band(tokens=("1", "1"))]}
    with pytest.raises(ValueError, match="binding"):
        event_bands(event, TORONTO, date(2026, 1, 2))


class Pages:
    def __init__(self, pages):
        self.pages, self.calls = iter(pages), []

    def read(self, path, params):
        self.calls.append((path, params))
        return next(self.pages)


def page(rows=(), next_cursor=None, more=False):
    return {"data": list(rows), "pagination": {"next_cursor": next_cursor, "has_more": more}}


def test_account_pages_keep_filters_and_native_cursors(tmp_path):
    store = store_at(tmp_path)
    http = Pages([page([{"type": "REWARD"}], "opaque/+==", True), page([{"type": "REDEEM"}])])
    filters = {"user": "0x" + "1" * 40, "exclude_deposits_withdrawals": "false", "start": 1}
    walk_pages(http, store, "/v2/activity", filters, label="activity", max_pages=3)
    assert http.calls[1][1] == {**filters, "cursor": "opaque/+=="}
    rows = records(store)
    assert [r["cursor_out"] for r in rows if r["kind"] == "account_page"] == ["opaque/+==", None]
    assert rows[-1]["kind"] == "account_walk_complete"


@pytest.mark.parametrize("pages", [
    [{"data": [], "pagination": {"has_more": False}}],
    [page(next_cursor="again", more=True), page(next_cursor="again", more=True)],
    [page(next_cursor=None, more=True)], [page(next_cursor="bad", more=False)],
    [page(next_cursor="not-terminal", more=True)],
])
def test_account_refuses_incomplete_or_repeated_cursor(tmp_path, pages):
    store = store_at(tmp_path)
    with pytest.raises(ValueError):
        walk_pages(Pages(pages), store, "/v2/activity", {}, label="test", max_pages=len(pages))
    assert not any(r["kind"] == "account_walk_complete" for r in records(store))


def test_account_full_scope_includes_cash_types_and_resolved_statuses(tmp_path):
    store = store_at(tmp_path)
    http = Pages([page()] * 7)
    args = SimpleNamespace(wallet="0x" + "A" * 40, page_size=500, from_utc=SimpleNamespace(timestamp=lambda: 1), max_pages=5)
    assert account_flow(args, store, http, 1000) == "account_export_complete"
    trades = http.calls[0][1]
    assert trades["taker_only"] == "false" and trades["start"] == 1 and trades["end"] == 1000
    all_activity, tip = http.calls[1][1], http.calls[2][1]
    assert "type" not in all_activity and all_activity["exclude_deposits_withdrawals"] == "false"
    assert tip["type"] == "TIP"
    statuses = [params for path, params in http.calls if path.endswith("positions")]
    assert {p["status"] for p in statuses} == {"OPEN", "CLOSED", "REDEEMABLE", "REDEEMABLE_LOST"}
    assert all(p["filter_amount"] == "0" for p in statuses)
    assert all("start" not in p and "end" not in p for p in statuses)
    result = records(store)[-1]
    assert result["pagination_complete"] and result["account_cash_reconciliation_proven"] is False


def test_import_closure_cannot_reach_auth_signing_or_orders():
    code = '''
import importlib.abc, sys
class Deny(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if (fullname.split('.')[0] in {'requests','dotenv','py_clob_client','polymarket','eth_account','web3','nacl'}
            or any(word in fullname.lower() for word in ('credential','signing','oauth','.auth','_auth','order_journal','re1_transport','lfc_'))
            or fullname.startswith('weather.market.') and not fullname.startswith('weather.market.pilot_')):
            raise RuntimeError('forbidden import ' + fullname)
sys.meta_path.insert(0, Deny())
import weather.market.pilot_validation_evidence
import weather.market.pilot_evidence_launch
assert not any(m.startswith(('requests', 'dotenv', 'eth_account', 'polymarket', 'py_clob_client')) for m in sys.modules)
print('public import closure PASS')
'''
    result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "public import closure PASS" in result.stdout


def test_command_contract_accepts_monday_flags(tmp_path):
    args = parser().parse_args([
        "public-capture", "--market", "denver", "--market", "toronto",
        "--event-date", "2026-11-10", "--event-date", "2026-11-11", "--all-bands", "--both-tokens",
        "--raw-market-stream", "--start-utc", "2026-11-08T23:55:00Z", "--end-utc", "2026-11-10T00:45:00Z",
        "--max-rest-rps", "2", "--output", str(tmp_path / "new")])
    assert args.market == ["denver", "toronto"] and args.max_rest_rps == 2
    assert args.end_utc.isoformat() == "2026-11-10T00:45:00+00:00"
