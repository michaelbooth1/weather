import csv
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import weather.market.market_microstructure as mm  # noqa: E402
from weather.market.market_microstructure import (  # noqa: E402
    audit_book_tape,
    capture_event_enrichment,
    clob_ensure_decision,
    clob_enrichment_health,
    clob_loop_health,
    clob_loop_command_matches,
    capture_event_books,
    capture_fleet_books_parallel,
    fleet_book_audit,
    fleet_effective_book_gap_seconds,
    price_history_rows,
    read_price_history_raw_response,
    record_market_websocket,
    repair_price_history_store,
    run_book_loop,
    run_enrichment_loop,
    running_clob_loop_processes,
    should_use_fast_interval,
    start_clob_loop_detached,
    stop_clob_loop_processes,
    summarize_order_book,
    token_rows_from_event,
)
from weather.market.market_microstructure_features import snapshot_band_key  # noqa: E402
from weather.market.market_config import config_for_date  # noqa: E402
from weather.io import writer_lock_path  # noqa: E402
from weather.operations.supervisor import acquire_writer_lock, release_writer_lock  # noqa: E402


def observed_runtime_command(command):
    if os.name == "nt" and sys.prefix != sys.base_prefix:
        return [str(Path(sys.base_prefix) / Path(command[0]).name), *command[1:]]
    return list(command)


def sample_event():
    return {
        "slug": "highest-temperature-in-toronto-on-june-12-2026",
        "title": "Highest temperature in Toronto on June 12, 2026",
        "markets": [
            {
                "id": "2501584",
                "conditionId": "0xabc",
                "question": "Will the highest temperature in Toronto be 20C or below on June 12?",
                "groupItemTitle": "20 C or below",
                "outcomes": json.dumps(["Yes", "No"]),
                "outcomePrices": json.dumps(["0.12", "0.88"]),
                "clobTokenIds": json.dumps(["yes-token", "no-token"]),
                "enableOrderBook": True,
                "active": True,
                "closed": False,
                "bestBid": "0.10",
                "bestAsk": "0.13",
                "lastTradePrice": "0.12",
                "volumeNum": "1000",
                "liquidityNum": "500",
            }
        ],
    }


class FakeClobClient:
    def __init__(self):
        self.book_requests = []
        self.history_requests = []

    def get_order_books(self, token_ids, batch_size=100):
        self.book_requests.append((list(token_ids), batch_size))
        return [
            {
                "market": "0xabc",
                "asset_id": token_id,
                "timestamp": "1781308800",
                "hash": f"hash-{token_id}",
                "bids": [{"price": "0.44", "size": "50"}, {"price": "0.43", "size": "150"}],
                "asks": [{"price": "0.46", "size": "40"}, {"price": "0.47", "size": "100"}],
                "min_order_size": "1",
                "tick_size": "0.01",
                "neg_risk": False,
                "last_trade_price": "0.45",
            }
            for token_id in token_ids
        ]

    def get_price_history(self, token_id, start_ts=None, end_ts=None, interval=None, fidelity_minutes=1):
        self.history_requests.append((token_id, start_ts, end_ts, interval, fidelity_minutes))
        return {"history": [{"t": 1781308800, "p": 0.45}]}


class FailingBookClient:
    def get_order_books(self, token_ids, batch_size=100):
        raise RuntimeError("book fetch failed")


class FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, value):
        self.sent.append(value)

    def recv(self):
        return json.dumps({
            "event_type": "price_change",
            "market": "0xabc",
            "price_changes": [
                {
                    "asset_id": "yes-token",
                    "price": "0.46",
                    "size": "12.5",
                    "side": "BUY",
                },
                {
                    "asset_id": "no-token",
                    "price": "0.54",
                    "trade_size": "7",
                    "side": "SELL",
                },
            ],
        })

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, pid=4321):
        self.pid = pid


class TestMarketMicrostructure(unittest.TestCase):
    def test_token_rows_extract_condition_and_clob_ids(self):
        captured_at = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)

        rows = token_rows_from_event(sample_event(), market_id="toronto", captured_at=captured_at)

        self.assertEqual(len(rows), 2)
        yes = next(row for row in rows if row["outcome"] == "Yes")
        no = next(row for row in rows if row["outcome"] == "No")
        self.assertEqual(yes["condition_id"], "0xabc")
        self.assertEqual(yes["clob_token_id"], "yes-token")
        self.assertEqual(no["clob_token_id"], "no-token")
        self.assertEqual(yes["bin_kind"], "lte")
        self.assertEqual(yes["bin_value"], 20)
        self.assertEqual(yes["gamma_yes"], 0.12)

    def test_summarize_order_book_derives_depth_and_execution_metrics(self):
        token = token_rows_from_event(sample_event())[0]
        book = {
            "market": "0xabc",
            "asset_id": "yes-token",
            "timestamp": "1781308800",
            "hash": "book-hash",
            "bids": [{"price": "0.44", "size": "50"}, {"price": "0.43", "size": "150"}],
            "asks": [{"price": "0.46", "size": "40"}, {"price": "0.47", "size": "100"}],
            "last_trade_price": "0.45",
        }

        row = summarize_order_book(book, token, datetime(2026, 6, 12, tzinfo=timezone.utc))

        self.assertAlmostEqual(row["best_bid"], 0.44)
        self.assertAlmostEqual(row["best_ask"], 0.46)
        self.assertAlmostEqual(row["spread"], 0.02)
        self.assertAlmostEqual(row["midpoint"], 0.45)
        self.assertAlmostEqual(row["bid_depth_all"], 200.0)
        self.assertAlmostEqual(row["ask_depth_all"], 140.0)
        self.assertAlmostEqual(row["buy_fillable_100"], 100.0)
        self.assertAlmostEqual(row["buy_vwap_100"], (40 * 0.46 + 60 * 0.47) / 100)
        self.assertAlmostEqual(row["sell_fillable_100"], 100.0)
        self.assertAlmostEqual(row["sell_vwap_100"], (50 * 0.44 + 50 * 0.43) / 100)

    def test_capture_event_books_writes_tokens_books_levels_history_and_ws_by_default(self):
        fake = FakeClobClient()
        fake_ws = FakeWebSocket()

        def factory(url, timeout=30):
            self.assertIn("/ws/market", url)
            self.assertEqual(timeout, mm.DEFAULT_WS_CONNECT_TIMEOUT)
            return fake_ws

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (root / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "snapshot_id",
                    "captured_at_utc",
                    "event_slug",
                    "range_label",
                    "bin_kind",
                    "bin_value_c",
                    "bin_value_hi",
                    "model_probability",
                    "market_yes",
                ])
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "snap1",
                    "captured_at_utc": "2026-06-12T15:00:00+00:00",
                    "event_slug": "highest-temperature-in-toronto-on-june-12-2026",
                    "range_label": "20 C or below",
                    "bin_kind": "lte",
                    "bin_value_c": "20",
                    "bin_value_hi": "",
                    "model_probability": "0.25",
                    "market_yes": "0.12",
                })
            result = capture_event_books(
                sample_event(),
                market_id="toronto",
                clob_client=fake,
                root=tmp,
                outcomes="yes",
                history_minutes=60,
                websocket_factory=factory,
                now=datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc),
            )
            token_rows = list(csv.DictReader((root / "clob_tokens.csv").open(encoding="utf-8", newline="")))
            summary_rows = list(csv.DictReader((root / "order_books_summary.csv").open(encoding="utf-8", newline="")))
            level_rows = list(csv.DictReader((root / "order_books_long.csv").open(encoding="utf-8", newline="")))
            history_rows = list(csv.DictReader((root / "price_history.csv").open(encoding="utf-8", newline="")))
            ws_rows = list(csv.DictReader((root / "market_ws_events.csv").open(encoding="utf-8", newline="")))
            clob_feature_rows = list(csv.DictReader((root / "clob_features_long.csv").open(encoding="utf-8", newline="")))
            status_rows = [
                json.loads(line)
                for line in (root / "clob_capture_status.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            raw_manifest_exists = (root / "price_history_raw_manifest.jsonl").exists()

        self.assertEqual(result["captured_tokens"], 1)
        self.assertEqual(result["books"], 1)
        self.assertEqual(result["raw_books_captured_at_utc"], "2026-06-12T15:00:00+00:00")
        self.assertEqual(result["derived_features_captured_at_utc"], "2026-06-12T15:00:00+00:00")
        self.assertEqual(result["ws_messages"], mm.DEFAULT_WS_MESSAGE_LIMIT)
        self.assertEqual(result["ws_event_rows"], mm.DEFAULT_WS_MESSAGE_LIMIT * 2)
        self.assertEqual(result["clob_feature_rows"], 1)
        self.assertEqual(len(token_rows), 2)
        self.assertEqual(summary_rows[0]["clob_token_id"], "yes-token")
        self.assertEqual(len(level_rows), 4)
        self.assertEqual(history_rows[0]["price"], "0.45")
        self.assertEqual(ws_rows[0]["asset_id"], "yes-token")
        self.assertEqual(ws_rows[0]["price"], "0.46")
        self.assertEqual(clob_feature_rows[0]["clob_feature_available"], "1.0")
        self.assertEqual(clob_feature_rows[0]["clob_best_bid"], "0.44")
        self.assertEqual(status_rows[0]["schema_version"], "clob_capture_status_v0.1")
        self.assertEqual(status_rows[0]["status"], "OK")
        self.assertEqual(status_rows[0]["captured_tokens"], 1)
        self.assertEqual(status_rows[0]["books"], 1)
        self.assertEqual(status_rows[0]["raw_books_captured_at_utc"], "2026-06-12T15:00:00+00:00")
        self.assertEqual(status_rows[0]["derived_features_captured_at_utc"], "2026-06-12T15:00:00+00:00")
        self.assertEqual(status_rows[0]["clob_feature_rows"], 1)
        self.assertEqual(status_rows[0]["price_history_new_points"], 1)
        self.assertEqual(status_rows[0]["price_history_duplicate_points"], 0)
        self.assertEqual(status_rows[0]["price_history_raw_response_count"], 1)
        self.assertTrue(status_rows[0]["price_history_raw_response_hashes"])
        self.assertTrue(status_rows[0]["capture_status_path"].endswith("clob_capture_status.jsonl"))
        self.assertTrue(raw_manifest_exists)
        self.assertEqual(fake.book_requests[0][0], ["yes-token"])
        self.assertEqual(fake.history_requests[0][0], "yes-token")

    def test_capture_market_books_uses_explicit_target_date(self):
        calls = {}

        class FakeEventClient:
            def __init__(self, timeout=10, target_date=None, market_id="toronto"):
                calls["target_date"] = target_date
                calls["market_id"] = market_id
                self.config = config_for_date(target_date, market_id)

            def get_event(self):
                event = sample_event()
                event["slug"] = self.config.event_slug
                return event

        def fake_validation_payload(target_date, markets, live_events, fetch_live):
            calls["validation_target_date"] = target_date.isoformat()
            calls["validation_markets"] = list(markets)
            calls["validation_fetch_live"] = fetch_live
            return {"validation_hash": "hash"}

        with tempfile.TemporaryDirectory() as tmp:
            with patch("weather.market.market_microstructure_capture.PolymarketClient", FakeEventClient), \
                    patch(
                        "weather.operations.event_metadata_validation.build_validation_payload",
                        side_effect=fake_validation_payload,
                    ), \
                    patch(
                        "weather.operations.event_metadata_validation.gate_for_market",
                        return_value={"ok": True},
                    ):
                result = mm.capture_market_books(
                    "austin",
                    target_date="2026-06-27",
                    clob_client=FakeClobClient(),
                    root=tmp,
                    include_price_history=False,
                    include_ws_events=False,
                    include_clob_features=False,
                )

        self.assertEqual(calls["target_date"], "2026-06-27")
        self.assertEqual(calls["market_id"], "austin")
        self.assertEqual(calls["validation_target_date"], "2026-06-27")
        self.assertEqual(calls["validation_markets"], ["austin"])
        self.assertFalse(calls["validation_fetch_live"])
        self.assertEqual(result["event_slug"], "highest-temperature-in-austin-on-june-27-2026")

    def test_parallel_raw_refresh_passes_explicit_target_date(self):
        seen = {}

        def fake_capture(market_id, **kwargs):
            seen[market_id] = kwargs.get("target_date")
            return {
                "market_id": market_id,
                "books": 1,
                "captured_at_utc": "2026-06-27T04:00:00+00:00",
            }

        payload = capture_fleet_books_parallel(
            market_id="toronto",
            target_date="2026-06-27",
            capture_fn=fake_capture,
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(seen, {"toronto": "2026-06-27"})

    def test_capture_event_books_writes_failure_status_before_reraising(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, "book fetch failed"):
                capture_event_books(
                    sample_event(),
                    market_id="toronto",
                    clob_client=FailingBookClient(),
                    root=tmp,
                    outcomes="yes",
                    include_price_history=False,
                    include_ws_events=False,
                    now=datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc),
                )
            status_rows = [
                json.loads(line)
                for line in (root / "clob_capture_status.jsonl").read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(status_rows[0]["status"], "ERROR")
        self.assertEqual(status_rows[0]["error_stage"], "order_books")
        self.assertIn("book fetch failed", status_rows[0]["error"])
        self.assertEqual(status_rows[0]["token_rows"], 2)
        self.assertEqual(status_rows[0]["captured_tokens"], 1)
        self.assertEqual(status_rows[0]["books"], 0)

    def test_capture_event_books_can_skip_derived_clob_feature_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "snapshots_long.csv").write_text(
                "snapshot_id,captured_at_utc,event_slug,range_label,bin_kind,bin_value_c,market_yes\n"
                "snap1,2026-06-12T15:00:00+00:00,highest-temperature-in-toronto-on-june-12-2026,20 C or below,lte,20,0.12\n",
                encoding="utf-8",
            )
            result = capture_event_books(
                sample_event(),
                market_id="toronto",
                clob_client=FakeClobClient(),
                root=tmp,
                outcomes="yes",
                include_price_history=False,
                include_ws_events=False,
                include_clob_features=False,
                now=datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc),
            )
            status_rows = [
                json.loads(line)
                for line in (root / "clob_capture_status.jsonl").read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(result["books"], 1)
        self.assertEqual(result["clob_feature_rows"], 0)
        self.assertFalse((root / "clob_features_long.csv").exists())
        self.assertFalse(status_rows[0]["include_clob_features"])

    def test_parallel_raw_refresh_fails_closed_on_cross_process_tape_contention(self):
        fake = FakeClobClient()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = mm.MarketMicrostructureStore(root=root, event_slug=sample_event()["slug"])
            lock_path = writer_lock_path(store.raw_tape_lock_anchor_path)
            lock_path.write_text(
                json.dumps({"pid": 424242, "operation": "external_raw_writer"}),
                encoding="utf-8",
            )

            def contended_capture(market_id, **kwargs):
                return capture_event_books(
                    sample_event(),
                    market_id=market_id,
                    clob_client=fake,
                    root=kwargs["root"],
                    outcomes=kwargs["outcomes"],
                    include_price_history=False,
                    include_ws_events=False,
                    include_clob_features=False,
                    now=datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc),
                )

            payload = capture_fleet_books_parallel(
                market_id="toronto",
                root=root,
                capture_fn=contended_capture,
                per_market_timeout_seconds=2,
            )
            row = payload["markets"][0]
            status = json.loads(
                (root / "clob_capture_status.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )

            self.assertEqual(len(fake.book_requests), 1, "network fetch must precede the short write lock")
            self.assertFalse((root / "clob_tokens.csv").exists())
            self.assertFalse((root / "order_books_summary.csv").exists())
            self.assertFalse((root / "order_books_long.csv").exists())
            self.assertFalse((root / "order_books.jsonl").exists())
            self.assertFalse(payload["ok"])
            self.assertEqual(row["status"], "BLOCK")
            self.assertTrue(row["raw_tape_write_blocked"])
            self.assertEqual(row["error_stage"], "raw_tape_write")
            self.assertIn("RawTapeWriterBusy", row["error"])
            self.assertEqual(status["error_stage"], "raw_tape_write")

    def test_enrichment_feature_reader_refuses_partial_raw_tape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "snapshots_long.csv").write_text(
                "snapshot_id,captured_at_utc,event_slug,range_label,bin_kind,bin_value_c,market_yes\n",
                encoding="utf-8",
            )
            store = mm.MarketMicrostructureStore(root=root, event_slug=sample_event()["slug"])
            writer_lock_path(store.raw_tape_lock_anchor_path).write_text(
                json.dumps({"pid": 424242, "operation": "external_raw_writer"}),
                encoding="utf-8",
            )

            with patch(
                "weather.market.market_microstructure_capture.write_clob_feature_rows"
            ) as write_features:
                result = capture_event_enrichment(
                    sample_event(),
                    market_id="toronto",
                    root=root,
                    outcomes="yes",
                    include_price_history=False,
                    include_ws_events=False,
                    include_clob_features=True,
                    now=datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc),
                )

            write_features.assert_not_called()
            self.assertEqual(result["status"], "DEGRADED")
            self.assertIn("RawTapeWriterBusy", result["clob_features_error"])
            self.assertFalse(result["raw_book_tape_touched"])

    def test_derived_clob_feature_failure_does_not_drop_raw_book_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "snapshots_long.csv").write_text(
                "snapshot_id,captured_at_utc,event_slug,range_label,bin_kind,bin_value_c,market_yes\n"
                "snap1,2026-06-12T15:00:00+00:00,highest-temperature-in-toronto-on-june-12-2026,20 C or below,lte,20,0.12\n",
                encoding="utf-8",
            )
            with patch(
                "weather.market.market_microstructure_capture.write_clob_feature_rows",
                side_effect=RuntimeError("feature builder failed"),
            ):
                result = capture_event_books(
                    sample_event(),
                    market_id="toronto",
                    clob_client=FakeClobClient(),
                    root=tmp,
                    outcomes="yes",
                    include_price_history=False,
                    include_ws_events=False,
                    now=datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc),
                )
            status_rows = [
                json.loads(line)
                for line in (root / "clob_capture_status.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            raw_books_exist = (root / "order_books_summary.csv").exists()

        self.assertEqual(result["books"], 1)
        self.assertEqual(result["raw_books_captured_at_utc"], "2026-06-12T15:00:00+00:00")
        self.assertIsNone(result["derived_features_captured_at_utc"])
        self.assertIn("feature builder failed", result["clob_features_error"])
        self.assertTrue(raw_books_exist)
        self.assertEqual(status_rows[0]["status"], "OK")
        self.assertIn("feature builder failed", status_rows[0]["clob_features_error"])

    def test_parallel_raw_refresh_skips_derived_features_and_reports_failed_market_lag(self):
        calls = []

        def fake_capture(market_id, **kwargs):
            calls.append((market_id, kwargs))
            self.assertFalse(kwargs["include_price_history"])
            self.assertFalse(kwargs["include_ws_events"])
            self.assertFalse(kwargs["include_clob_features"])
            if market_id == "nyc":
                raise RuntimeError("book endpoint unavailable")
            return {
                "market_id": market_id,
                "books": 2,
                "captured_at_utc": "2026-06-12T15:00:00+00:00",
                "raw_books_captured_at_utc": "2026-06-12T15:00:00+00:00",
            }

        with patch(
            "weather.market.market_microstructure_capture.all_specs",
            return_value=[SimpleNamespace(id="toronto"), SimpleNamespace(id="nyc")],
        ):
            payload = capture_fleet_books_parallel(
                market_id="all",
                capture_fn=fake_capture,
                max_workers=2,
                per_market_timeout_seconds=5,
            )

        by_market = {row["market_id"]: row for row in payload["markets"]}
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["summary"]["ok_market_count"], 1)
        self.assertEqual(payload["summary"]["failed_markets"], ["nyc"])
        self.assertTrue(by_market["toronto"]["raw_book_refresh_ok"])
        self.assertIsNotNone(by_market["toronto"]["raw_book_age_seconds_at_finish"])
        self.assertIn("book endpoint unavailable", by_market["nyc"]["error"])
        self.assertEqual(sorted(market for market, _kwargs in calls), ["nyc", "toronto"])

    def test_parallel_raw_refresh_returns_at_deadline_and_preserves_per_market_timeout(self):
        slow_finished = threading.Event()

        def fake_capture(market_id, **_kwargs):
            if market_id == "nyc":
                time.sleep(0.15)
                slow_finished.set()
            return {
                "market_id": market_id,
                "books": 1,
                "captured_at_utc": "2026-06-12T15:00:00+00:00",
            }

        started = time.perf_counter()
        with patch(
            "weather.market.market_microstructure_capture.all_specs",
            return_value=[SimpleNamespace(id="toronto"), SimpleNamespace(id="nyc")],
        ):
            payload = capture_fleet_books_parallel(
                market_id="all",
                capture_fn=fake_capture,
                max_workers=2,
                per_market_timeout_seconds=0.03,
                freshness_sla_seconds=0.1,
            )
        elapsed = time.perf_counter() - started

        by_market = {row["market_id"]: row for row in payload["markets"]}
        self.assertLess(elapsed, 0.12)
        self.assertTrue(by_market["toronto"]["raw_book_refresh_ok"])
        self.assertTrue(by_market["nyc"]["timeout"])
        self.assertEqual(payload["summary"]["timeout_markets"], ["nyc"])
        self.assertTrue(payload["inside_freshness_sla"])
        self.assertTrue(slow_finished.wait(timeout=1.0))
        time.sleep(0.01)

    def test_timed_out_raw_market_cannot_overlap_next_tape_writer(self):
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        calls = []

        def fake_capture(market_id, **_kwargs):
            calls.append(market_id)
            entered.set()
            release.wait(timeout=1.0)
            finished.set()
            return {
                "market_id": market_id,
                "books": 1,
                "captured_at_utc": "2026-06-12T15:00:00+00:00",
            }

        first = capture_fleet_books_parallel(
            market_id="toronto",
            capture_fn=fake_capture,
            max_workers=1,
            per_market_timeout_seconds=0.02,
        )
        self.assertTrue(entered.is_set())
        second = capture_fleet_books_parallel(
            market_id="toronto",
            capture_fn=fake_capture,
            max_workers=1,
            per_market_timeout_seconds=0.02,
        )
        release.set()
        self.assertTrue(finished.wait(timeout=1.0))
        time.sleep(0.01)

        self.assertTrue(first["markets"][0]["timeout"])
        self.assertTrue(second["markets"][0]["prior_capture_still_running"])
        self.assertIn("PreviousRawCaptureActive", second["markets"][0]["error"])
        self.assertEqual(calls, ["toronto"])

    def test_enrichment_capture_never_fetches_or_writes_raw_book_tape(self):
        class NoBookClient(FakeClobClient):
            def get_order_books(self, *_args, **_kwargs):
                raise AssertionError("enrichment attempted raw book fetch")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = NoBookClient()
            result = capture_event_enrichment(
                sample_event(),
                market_id="toronto",
                clob_client=client,
                root=root,
                include_price_history=True,
                include_ws_events=False,
                include_clob_features=False,
                now=datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc),
            )
            status = json.loads(
                (root / "clob_enrichment_status.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )
            raw_paths_exist = {
                name: (root / name).exists()
                for name in (
                    "order_books_summary.csv",
                    "order_books_long.csv",
                    "order_books.jsonl",
                    "clob_tokens.csv",
                )
            }

        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["raw_book_tape_touched"])
        self.assertEqual(client.book_requests, [])
        self.assertFalse(any(raw_paths_exist.values()))
        self.assertEqual(status["mode"], "research_enrichment")
        self.assertEqual(status["schema_version"], "clob_enrichment_capture_status_v0.1")

    def test_enrichment_token_failure_is_degraded_without_losing_other_history(self):
        class PartialHistoryClient(FakeClobClient):
            def get_price_history(self, token_id, **kwargs):
                if token_id == "no-token":
                    raise RuntimeError("history unavailable")
                return super().get_price_history(token_id, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            result = capture_event_enrichment(
                sample_event(),
                market_id="toronto",
                clob_client=PartialHistoryClient(),
                root=tmp,
                include_price_history=True,
                include_ws_events=False,
                include_clob_features=False,
                now=datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(result["price_history_rows"], 1)
        self.assertEqual(result["price_history_error_count"], 1)
        self.assertIn("history unavailable", result["error"])

    def test_websocket_failure_does_not_drop_rest_book_capture(self):
        def failing_websocket(_url, timeout=30):
            raise RuntimeError("websocket unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = capture_event_books(
                sample_event(),
                market_id="toronto",
                clob_client=FakeClobClient(),
                root=tmp,
                outcomes="yes",
                websocket_factory=failing_websocket,
                now=datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc),
            )
            status_rows = [
                json.loads(line)
                for line in (root / "clob_capture_status.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            summary_rows = list(csv.DictReader((root / "order_books_summary.csv").open(encoding="utf-8", newline="")))
            history_rows = list(csv.DictReader((root / "price_history.csv").open(encoding="utf-8", newline="")))

        self.assertEqual(result["books"], 1)
        self.assertEqual(result["price_history_rows"], 1)
        self.assertEqual(result["ws_messages"], 0)
        self.assertIn("websocket unavailable", result["ws_error"])
        self.assertEqual(status_rows[0]["status"], "OK")
        self.assertIn("websocket unavailable", status_rows[0]["ws_error"])
        self.assertEqual(len(summary_rows), 1)
        self.assertEqual(len(history_rows), 1)

    def test_snapshot_band_key_reads_new_upper_endpoint_column(self):
        self.assertEqual(
            snapshot_band_key({
                "range_label": "90 F",
                "bin_kind": "eq",
                "bin_value_c": "90",
                "bin_value_hi_c": "91",
            }),
            ("eq", 90, 91),
        )

    def test_price_history_rows_normalize_point_time(self):
        token = token_rows_from_event(sample_event())[0]

        rows = price_history_rows(
            {"history": [{"t": 1781308800, "p": "0.45"}]},
            token,
            datetime(2026, 6, 12, tzinfo=timezone.utc),
            interval="1m",
            fidelity_minutes=1,
        )

        self.assertEqual(rows[0]["interval"], "1m")
        self.assertEqual(rows[0]["price"], 0.45)
        self.assertIn("2026", rows[0]["point_time_utc"])

    def test_price_history_writer_dedupes_overlapping_windows(self):
        token = token_rows_from_event(sample_event())[0]
        first_capture = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)
        second_capture = datetime(2026, 6, 12, 15, 1, tzinfo=timezone.utc)

        first_response = {"history": [{"t": 1781308800, "p": 0.45}, {"t": 1781308860, "p": 0.46}]}
        second_response = {"history": [{"t": 1781308860, "p": 0.46}, {"t": 1781308920, "p": 0.47}]}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = mm.MarketMicrostructureStore(root=root, event_slug=token["event_slug"])
            first = store.write_price_history(
                price_history_rows(first_response, token, first_capture, interval="1m", fidelity_minutes=1),
                [{
                    "captured_at_utc": first_capture.isoformat(),
                    "event_slug": token["event_slug"],
                    "market_id": token["market_id"],
                    "clob_token_id": token["clob_token_id"],
                    "interval": "1m",
                    "fidelity_minutes": 1,
                    "response": first_response,
                }],
            )
            second = store.write_price_history(
                price_history_rows(second_response, token, second_capture, interval="1m", fidelity_minutes=1),
                [{
                    "captured_at_utc": second_capture.isoformat(),
                    "event_slug": token["event_slug"],
                    "market_id": token["market_id"],
                    "clob_token_id": token["clob_token_id"],
                    "interval": "1m",
                    "fidelity_minutes": 1,
                    "response": second_response,
                }],
            )
            rows = list(csv.DictReader((root / "price_history.csv").open(encoding="utf-8", newline="")))

        self.assertEqual(first["price_history_new_points"], 2)
        self.assertEqual(second["price_history_new_points"], 1)
        self.assertEqual(second["price_history_duplicate_points"], 1)
        self.assertEqual(second["price_history_corrected_points"], 0)
        self.assertEqual(second["price_history_total_points"], 3)
        self.assertEqual(len(rows), 3)
        self.assertEqual([row["price"] for row in rows], ["0.45", "0.46", "0.47"])

    def test_price_history_writer_updates_corrected_point_without_duplicate_row(self):
        token = token_rows_from_event(sample_event())[0]
        first_capture = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)
        second_capture = datetime(2026, 6, 12, 15, 2, tzinfo=timezone.utc)
        original = {"history": [{"t": 1781308800, "p": 0.45}]}
        corrected = {"history": [{"t": 1781308800, "p": 0.46}]}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = mm.MarketMicrostructureStore(root=root, event_slug=token["event_slug"])
            store.write_price_history(
                price_history_rows(original, token, first_capture, interval="1m", fidelity_minutes=1),
                [],
            )
            result = store.write_price_history(
                price_history_rows(corrected, token, second_capture, interval="1m", fidelity_minutes=1),
                [],
            )
            rows = list(csv.DictReader((root / "price_history.csv").open(encoding="utf-8", newline="")))

        self.assertEqual(result["price_history_new_points"], 0)
        self.assertEqual(result["price_history_duplicate_points"], 0)
        self.assertEqual(result["price_history_corrected_points"], 1)
        self.assertEqual(result["price_history_total_points"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price"], "0.46")

    def test_price_history_raw_responses_are_content_addressed_and_reused(self):
        token = token_rows_from_event(sample_event())[0]
        captured_at = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)
        response = {"history": [{"t": 1781308800, "p": 0.45}]}
        raw_record = {
            "captured_at_utc": captured_at.isoformat(),
            "event_slug": token["event_slug"],
            "market_id": token["market_id"],
            "clob_token_id": token["clob_token_id"],
            "interval": "1m",
            "fidelity_minutes": 1,
            "response": response,
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = mm.MarketMicrostructureStore(root=root, event_slug=token["event_slug"])
            first = store.write_price_history([], [raw_record])
            second = store.write_price_history([], [raw_record])
            blobs = list((root / "price_history_raw").glob("*.json"))
            legacy_rows = [
                json.loads(line)
                for line in (root / "price_history.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            restored = read_price_history_raw_response(legacy_rows[-1], root=root)

        self.assertEqual(first["price_history_raw_response_new_blob_count"], 1)
        self.assertEqual(second["price_history_raw_response_new_blob_count"], 0)
        self.assertEqual(second["price_history_raw_response_reused_count"], 1)
        self.assertEqual(first["price_history_raw_response_hashes"], second["price_history_raw_response_hashes"])
        self.assertEqual(len(blobs), 1)
        self.assertNotIn("response", legacy_rows[0])
        self.assertEqual(restored, response)

    def test_price_history_repair_writes_deduped_sidecar_with_key_parity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                {
                    "event_slug": "event",
                    "market_id": "toronto",
                    "clob_token_id": "yes-token",
                    "fidelity_minutes": "1",
                    "interval": "1m",
                    "point_timestamp": "1781308800",
                    "point_time_utc": "2026-06-12T00:00:00+00:00",
                    "price": "0.45",
                },
                {
                    "event_slug": "event",
                    "market_id": "toronto",
                    "clob_token_id": "yes-token",
                    "fidelity_minutes": "1",
                    "interval": "1m",
                    "point_timestamp": "1781308800",
                    "point_time_utc": "2026-06-12T00:00:00+00:00",
                    "price": "0.45",
                },
                {
                    "event_slug": "event",
                    "market_id": "toronto",
                    "clob_token_id": "yes-token",
                    "fidelity_minutes": "1",
                    "interval": "1m",
                    "point_timestamp": "1781308860",
                    "point_time_utc": "2026-06-12T00:01:00+00:00",
                    "price": "0.46",
                },
            ]
            with (root / "price_history.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)

            result = repair_price_history_store(root, generated_at_utc="2026-06-23T00:00:00+00:00")
            source_rows = list(csv.DictReader((root / "price_history.csv").open(encoding="utf-8", newline="")))
            deduped_rows = list(csv.DictReader((root / "price_history_deduped.csv").open(encoding="utf-8", newline="")))

        self.assertEqual(result["schema_version"], "clob_price_history_repair_v0.1")
        self.assertEqual(result["input_rows"], 3)
        self.assertEqual(result["deduped_rows"], 2)
        self.assertEqual(result["duplicate_rows_reclaimed"], 1)
        self.assertEqual(result["validation"]["status"], "PASS")
        self.assertEqual(len(source_rows), 3)
        self.assertEqual(len(deduped_rows), 2)

    def test_websocket_recorder_subscribes_to_assets_and_writes_raw_event(self):
        fake_ws = FakeWebSocket()

        def factory(url, timeout=30):
            self.assertIn("/ws/market", url)
            self.assertEqual(timeout, 30)
            return fake_ws

        with tempfile.TemporaryDirectory() as tmp:
            result = record_market_websocket(
                sample_event(),
                market_id="toronto",
                root=tmp,
                outcomes="yes",
                seconds=30,
                message_limit=1,
                websocket_factory=factory,
            )
            rows = list(csv.DictReader((Path(tmp) / "market_ws_events.csv").open(encoding="utf-8", newline="")))

        sent = json.loads(fake_ws.sent[0])
        self.assertEqual(sent["operation"], "subscribe")
        self.assertEqual(sent["assets_ids"], ["yes-token"])
        self.assertTrue(fake_ws.closed)
        self.assertEqual(result["messages"], 1)
        self.assertEqual(result["event_rows"], 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["event_type"], "price_change")
        self.assertEqual(rows[0]["asset_id"], "yes-token")
        self.assertEqual(rows[0]["price"], "0.46")
        self.assertEqual(rows[0]["size"], "12.5")
        self.assertEqual(rows[1]["asset_id"], "no-token")
        self.assertEqual(rows[1]["trade_size"], "7")

    def test_fast_interval_triggers_on_large_midpoint_change(self):
        config = config_for_date("2026-06-12", "toronto")
        now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)

        fast = should_use_fast_interval(
            [config],
            now,
            {"yes-token": 0.40},
            {"yes-token": 0.47},
            fast_hours_before_close=None,
            fast_after_local_hour=None,
            fast_on_mid_change_bps=500,
        )

        self.assertTrue(fast)

    def test_clob_loop_health_states(self):
        now = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)
        base = {
            "pid": 123,
            "started_at": now.isoformat(),
            "last_heartbeat": now.isoformat(),
            "interval_seconds": 60,
            "consecutive_errors": 0,
            "error_markets": [],
        }

        self.assertEqual(clob_loop_health(base, now=now)["state"], "RUNNING")
        split = clob_loop_health({
            **base,
            "last_raw_books_captured_at": (now - timedelta(seconds=10)).isoformat(),
            "last_raw_books_by_market": {"toronto": (now - timedelta(seconds=10)).isoformat()},
            "raw_book_useful_iterations": 3,
            "last_derived_features_captured_at": (now - timedelta(seconds=70)).isoformat(),
            "last_derived_features_by_market": {"toronto": (now - timedelta(seconds=70)).isoformat()},
            "derived_feature_error_markets": ["nyc"],
        }, now=now)
        self.assertEqual(split["last_raw_books_age_seconds"], 10.0)
        self.assertEqual(split["raw_book_market_ages_seconds"]["toronto"], 10.0)
        self.assertEqual(split["raw_book_useful_iterations"], 3)
        self.assertEqual(split["last_derived_features_age_seconds"], 70.0)
        self.assertEqual(split["derived_feature_error_markets"], ["nyc"])
        self.assertEqual(clob_loop_health({**base, "error_markets": ["nyc"]}, now=now)["state"], "DEGRADED")
        zero_capture = {
            **base,
            "last_market_results": {
                "toronto": {"books": 0, "captured_tokens": 0},
                "nyc": {"books": 0, "captured_tokens": 0},
            },
        }
        self.assertEqual(clob_loop_health(zero_capture, now=now)["state"], "DEGRADED")
        self.assertEqual(clob_loop_health(zero_capture, now=now)["discovery_sanity"]["status"], "BLOCK")
        target_mismatch = {
            **base,
            "target_date": "2026-06-27",
            "date_selection": "fixed_target_date",
            "last_market_results": {
                "los-angeles": {
                    "event_slug": "highest-temperature-in-los-angeles-on-june-26-2026",
                    "target_date": "2026-06-26",
                    "books": 22,
                    "captured_tokens": 22,
                },
            },
        }
        target_health = clob_loop_health(target_mismatch, now=now)
        self.assertEqual(target_health["state"], "DEGRADED")
        self.assertEqual(target_health["target_date_mismatch_markets"], ["los-angeles"])
        self.assertEqual(target_health["last_target_dates_by_market"]["los-angeles"], "2026-06-26")
        self.assertEqual(clob_loop_health({**base, "consecutive_errors": 3}, now=now)["state"], "ERRORING")
        stale = {**base, "last_heartbeat": (now - timedelta(seconds=181)).isoformat()}
        self.assertEqual(clob_loop_health(stale, now=now)["state"], "DEAD")
        slow_cycle = {
            **base,
            "last_heartbeat": (now - timedelta(seconds=181)).isoformat(),
            "last_iteration_elapsed_seconds": 160.0,
            "max_recent_iteration_elapsed_seconds": 170.0,
            "last_sleep_seconds": 60.0,
        }
        slow_cycle_health = clob_loop_health(slow_cycle, now=now)
        self.assertEqual(slow_cycle_health["state"], "RUNNING")
        self.assertEqual(slow_cycle_health["recent_iteration_elapsed_seconds"], 170.0)
        self.assertEqual(slow_cycle_health["dead_after_seconds"], 260.0)
        self.assertEqual(clob_loop_health(None, now=now)["state"], "UNKNOWN")

    def test_clob_ensure_decision(self):
        self.assertEqual(clob_ensure_decision("RUNNING", True), "noop")
        self.assertEqual(clob_ensure_decision("RUNNING", False), "restart")
        self.assertEqual(clob_ensure_decision("DEGRADED", True), "noop")
        self.assertEqual(clob_ensure_decision("ERRORING", True), "noop")
        self.assertEqual(clob_ensure_decision("DEAD", True), "restart")
        self.assertEqual(clob_ensure_decision("UNKNOWN", False), "start")
        self.assertEqual(clob_ensure_decision("RUNNING", True, has_orphan_processes=True), "restart")
        self.assertEqual(clob_ensure_decision("RUNNING", True, runtime_matches_current=False), "restart")
        self.assertEqual(clob_ensure_decision("RUNNING", True, target_mode_mismatch=True), "restart")
        self.assertEqual(
            clob_ensure_decision("RUNNING", True, writer_lock_healthy=False),
            "restart",
        )

    def test_ensure_clob_loop_backoff_blocks_repeated_runtime_restart(self):
        now = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "clob_loop_status.json"
            diagnostics_path = root / "clob_diagnostics.jsonl"
            console_path = root / "clob_loop_console.log"
            status_path.write_text(
                json.dumps({
                    "pid": 4321,
                    "last_heartbeat": now.isoformat(),
                    "interval_seconds": 60,
                    "consecutive_errors": 0,
                    "runtime_identity": {"source_fingerprint": "old"},
                }),
                encoding="utf-8",
            )
            status_path.with_name(".clob_loop_status.json.writer.lock").write_text(
                json.dumps({"pid": 4321}),
                encoding="utf-8",
            )
            diagnostics_path.write_text(
                json.dumps({
                    "time": (now - timedelta(seconds=30)).isoformat(),
                    "supervisor": "ensure",
                    "action": "restart",
                    "state": "RUNNING",
                }) + "\n",
                encoding="utf-8",
            )
            console_path.write_text("", encoding="utf-8")

            with patch.object(mm, "CLOB_LOOP_STATUS_PATH", status_path), \
                    patch.object(mm, "CLOB_DIAGNOSTICS_PATH", diagnostics_path), \
                    patch.object(mm, "CLOB_LOOP_CONSOLE_LOG_PATH", console_path), \
                    patch.object(mm, "CLOB_PAUSE_FLAG_PATH", root / "pause.flag"), \
                    patch.object(mm, "CLOB_SUPERVISOR_LOCK_PATH", root / "supervisor.lock"), \
                    patch.object(mm, "acquire_clob_supervisor_lock", return_value=object()), \
                    patch.object(mm, "release_clob_supervisor_lock"), \
                    patch.object(mm, "pid_is_python", return_value=True), \
                    patch.object(mm, "running_clob_loop_processes", return_value=[]), \
                    patch.object(mm, "clob_runtime_matches_current", return_value=False), \
                    patch.object(mm, "stop_clob_loop") as stop_loop, \
                    patch.object(mm, "start_clob_loop_detached") as start_loop:
                result = mm.ensure_clob_loop(now=now)

        self.assertEqual(result["action"], "backoff")
        self.assertEqual(result["intended_action"], "restart")
        self.assertEqual(result["restart_cause"], "runtime_identity")
        self.assertEqual(result["ensure_status"], "BLOCKED")
        self.assertEqual(result["exit_code"], 1)
        stop_loop.assert_not_called()
        start_loop.assert_not_called()

    def test_ensure_clob_loop_restarts_fixed_target_date_as_rolling_in_auto_mode(self):
        now = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "clob_loop_status.json"
            status_path.write_text(
                json.dumps({
                    "pid": 4321,
                    "last_heartbeat": now.isoformat(),
                    "interval_seconds": 60,
                    "consecutive_errors": 0,
                    "runtime_identity": {"source_fingerprint": "old"},
                    "target_date": "2026-06-27",
                    "date_selection": "fixed_target_date",
                    "last_market_results": {
                        "austin": {
                            "books": 1,
                            "captured_tokens": 2,
                            "target_date": "2026-06-27",
                        },
                    },
                }),
                encoding="utf-8",
            )
            status_path.with_name(".clob_loop_status.json.writer.lock").write_text(
                json.dumps({"pid": 4321}),
                encoding="utf-8",
            )

            with patch.object(mm, "CLOB_LOOP_STATUS_PATH", status_path), \
                    patch.object(mm, "CLOB_DIAGNOSTICS_PATH", root / "clob_diagnostics.jsonl"), \
                    patch.object(mm, "CLOB_LOOP_CONSOLE_LOG_PATH", root / "clob_loop_console.log"), \
                    patch.object(mm, "CLOB_PAUSE_FLAG_PATH", root / "pause.flag"), \
                    patch.object(mm, "CLOB_SUPERVISOR_LOCK_PATH", root / "supervisor.lock"), \
                    patch.object(mm, "acquire_clob_supervisor_lock", return_value=object()), \
                    patch.object(mm, "release_clob_supervisor_lock"), \
                    patch.object(mm, "pid_is_python", return_value=True), \
                    patch.object(mm, "running_clob_loop_processes", return_value=[]), \
                    patch.object(mm, "clob_runtime_matches_current", return_value=False), \
                    patch.object(mm, "supervisor_recovery_guard", return_value={"allowed": True}), \
                    patch.object(mm, "loop_file_offsets", return_value={}), \
                    patch.object(mm, "quarantine_malformed_loop_lines", return_value={"quarantined": 0}), \
                    patch.object(mm, "stop_clob_loop", return_value={"stopped": True}) as stop_loop, \
                    patch.object(mm, "start_clob_loop_detached", return_value={"started": True}) as start_loop:
                result = mm.ensure_clob_loop(now=now)

        self.assertEqual(result["action"], "restart")
        self.assertFalse(result["preserved_target_date_from_status"])
        self.assertTrue(result["target_mode_mismatch"])
        self.assertEqual(result["status_target_date"], "2026-06-27")
        self.assertEqual(result["restart_cause"], "target_date_mode_mismatch")
        stop_loop.assert_called_once()
        start_loop.assert_called_once()
        self.assertIsNone(start_loop.call_args.kwargs["target_date"])

    def test_ensure_clob_loop_noop_does_not_scan_log_offsets(self):
        now = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "clob_loop_status.json"
            status_path.write_text(
                json.dumps({
                    "pid": 4321,
                    "last_heartbeat": now.isoformat(),
                    "interval_seconds": 60,
                    "consecutive_errors": 0,
                    "runtime_identity": {"source_fingerprint": "current"},
                    "last_market_results": {
                        "toronto": {"books": 1, "captured_tokens": 2, "error": None},
                    },
                }),
                encoding="utf-8",
            )
            status_path.with_name(".clob_loop_status.json.writer.lock").write_text(
                json.dumps({"pid": 4321}),
                encoding="utf-8",
            )

            with patch.object(mm, "CLOB_LOOP_STATUS_PATH", status_path), \
                    patch.object(mm, "CLOB_DIAGNOSTICS_PATH", root / "clob_diagnostics.jsonl"), \
                    patch.object(mm, "CLOB_LOOP_CONSOLE_LOG_PATH", root / "clob_loop_console.log"), \
                    patch.object(mm, "CLOB_PAUSE_FLAG_PATH", root / "pause.flag"), \
                    patch.object(mm, "CLOB_SUPERVISOR_LOCK_PATH", root / "supervisor.lock"), \
                    patch.object(mm, "acquire_clob_supervisor_lock", return_value=object()), \
                    patch.object(mm, "release_clob_supervisor_lock"), \
                    patch.object(mm, "pid_is_python", return_value=True), \
                    patch.object(mm, "running_clob_loop_processes", return_value=[]), \
                    patch.object(mm, "clob_runtime_matches_current", return_value=True), \
                    patch.object(mm, "loop_file_offsets", side_effect=AssertionError("noop scanned log offsets")):
                result = mm.ensure_clob_loop(now=now)

        self.assertEqual(result["action"], "noop")
        self.assertNotIn("loop_offsets_before", result)

    def test_ensure_clob_loop_dead_pid_is_not_misclassified_as_benign_stale_code(self):
        now = datetime(2026, 7, 13, 16, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "clob_loop_status.json"
            status_path.write_text(
                json.dumps({
                    "pid": 4321,
                    "last_heartbeat": now.isoformat(),
                    "interval_seconds": 60,
                    "consecutive_errors": 0,
                    "runtime_identity": {"source_fingerprint": "stale"},
                }),
                encoding="utf-8",
            )
            with patch.object(mm, "CLOB_LOOP_STATUS_PATH", status_path), \
                    patch.object(mm, "CLOB_DIAGNOSTICS_PATH", root / "clob_diagnostics.jsonl"), \
                    patch.object(mm, "CLOB_LOOP_CONSOLE_LOG_PATH", root / "clob_loop_console.log"), \
                    patch.object(mm, "CLOB_PAUSE_FLAG_PATH", root / "pause.flag"), \
                    patch.object(mm, "CLOB_SUPERVISOR_LOCK_PATH", root / "supervisor.lock"), \
                    patch.object(mm, "acquire_clob_supervisor_lock", return_value=object()), \
                    patch.object(mm, "release_clob_supervisor_lock"), \
                    patch.object(mm, "pid_is_python", return_value=False), \
                    patch.object(mm, "running_clob_loop_processes", return_value=[]), \
                    patch.object(mm, "clob_runtime_matches_current", return_value=False), \
                    patch.object(mm, "supervisor_recovery_guard", return_value={"allowed": True}), \
                    patch.object(mm, "loop_file_offsets", return_value={}), \
                    patch.object(mm, "quarantine_malformed_loop_lines", return_value={}), \
                    patch.object(mm, "stop_clob_loop") as stop_loop, \
                    patch.object(mm, "start_clob_loop_detached", return_value={"started": True}) as start_loop:
                result = mm.ensure_clob_loop(now=now)

        self.assertEqual(result["action"], "start")
        self.assertEqual(result["state"], "DEAD")
        self.assertEqual(result["restart_cause"], "DEAD")
        self.assertEqual(result["exit_code"], 0)
        stop_loop.assert_not_called()
        start_loop.assert_called_once()

    def test_ensure_clob_loop_lock_contention_is_persisted_and_nonzero(self):
        now = datetime(2026, 7, 13, 16, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(mm, "CLOB_LOOP_STATUS_PATH", root / "clob_loop_status.json"), \
                    patch.object(mm, "CLOB_DIAGNOSTICS_PATH", root / "clob_diagnostics.jsonl"), \
                    patch.object(mm, "CLOB_LOOP_CONSOLE_LOG_PATH", root / "clob_loop_console.log"), \
                    patch.object(mm, "CLOB_PAUSE_FLAG_PATH", root / "pause.flag"), \
                    patch.object(mm, "CLOB_SUPERVISOR_LOCK_PATH", root / "supervisor.lock"), \
                    patch.object(mm, "acquire_clob_supervisor_lock", return_value=None), \
                    patch.object(mm, "start_clob_loop_detached") as start_loop:
                result = mm.ensure_clob_loop(now=now)
                persisted = json.loads(
                    (root / "clob_loop_supervisor_status.json").read_text(encoding="utf-8")
                )

        self.assertEqual(result["action"], "locked")
        self.assertEqual(result["ensure_status"], "BLOCKED")
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(persisted["action"], "locked")
        start_loop.assert_not_called()

    def test_ensure_clob_cli_returns_persisted_nonzero_exit_code(self):
        result = {"action": "backoff", "ensure_status": "BLOCKED", "exit_code": 1}
        with patch.object(mm, "ensure_clob_loop", return_value=result), \
                patch.object(sys, "argv", ["market_microstructure", "ensure"]), \
                patch("builtins.print"):
            exit_code = mm.main()

        self.assertEqual(exit_code, 1)

    def test_running_clob_loop_processes_filters_loop_commands(self):
        rows = [
            {"pid": 100, "name": "pythonw.exe", "command_line": "pythonw.exe -m weather.market.market_microstructure loop --market all"},
            {"pid": 101, "name": "pythonw.exe", "command_line": "pythonw.exe -m weather.market.market_microstructure ensure --market all"},
            {"pid": 102, "name": "python.exe", "command_line": "python.exe app.py"},
            {"pid": 103, "name": "pythonw.exe", "command_line": "pythonw.exe -m weather.market.market_microstructure loop --market toronto"},
        ]

        matches = running_clob_loop_processes(process_rows=rows, current_pid=999)

        self.assertTrue(clob_loop_command_matches(rows[0]["command_line"]))
        self.assertFalse(clob_loop_command_matches(rows[1]["command_line"]))
        self.assertEqual([row["pid"] for row in matches], [100, 103])

    def test_managed_loop_command_declares_raw_only_deadline_contract(self):
        command = mm._clob_loop_command()

        self.assertNotIn("--price-history", command)
        self.assertNotIn("--no-price-history", command)
        self.assertNotIn("--websocket-events", command)
        self.assertNotIn("--no-websocket-events", command)
        self.assertNotIn("--websocket-seconds", command)
        self.assertNotIn("--websocket-message-limit", command)
        self.assertNotIn("--websocket-heartbeat-seconds", command)
        self.assertNotIn("--websocket-connect-timeout", command)
        self.assertEqual(command[command.index("--raw-max-workers") + 1], "12")
        self.assertEqual(
            command[command.index("--raw-market-timeout-seconds") + 1],
            "20.0",
        )

    def test_managed_loop_command_is_accepted_by_raw_only_cli(self):
        command = mm._clob_loop_command()

        with (
            patch.object(sys, "argv", [command[2], *command[3:]]),
            patch.object(mm, "configure_json_console_logging"),
            patch.object(mm, "run_book_loop") as run_loop,
        ):
            mm.main()

        run_loop.assert_called_once()
        kwargs = run_loop.call_args.kwargs
        self.assertFalse(kwargs["include_price_history"])
        self.assertFalse(kwargs["include_ws_events"])
        self.assertEqual(kwargs["raw_max_workers"], 12)
        self.assertEqual(kwargs["raw_market_timeout_seconds"], 20.0)

    def test_managed_loop_command_reconstruction_uses_persisted_nondefault_fields(self):
        status_payload = {
            "market_id": "nyc",
            "target_date": "2026-06-27",
            "interval_seconds": 47.0,
            "fast_interval_seconds": 13.0,
            "fast_hours_before_close": 3.0,
            "fast_after_local_hour": 14.5,
            "fast_on_mid_change_bps": 321.0,
            "outcomes": "yes",
            "batch_size": 17,
            "include_price_history": False,
            "include_ws_events": False,
            "websocket_seconds": 19.0,
            "websocket_message_limit": 23,
            "websocket_heartbeat_seconds": 11.0,
            "websocket_connect_timeout": 7.0,
            "raw_max_workers": 5,
            "raw_market_timeout_seconds": 18.0,
        }
        with patch.object(mm, "_clob_loop_command", return_value=["managed"]) as build:
            command = mm._clob_loop_command_from_status(status_payload)

        self.assertEqual(command, ["managed"])
        self.assertEqual(build.call_args.kwargs["market_id"], "nyc")
        self.assertEqual(build.call_args.kwargs["interval_seconds"], 47.0)
        self.assertEqual(build.call_args.kwargs["ws_seconds"], 19.0)
        self.assertEqual(build.call_args.kwargs["ws_message_limit"], 23)
        self.assertEqual(build.call_args.kwargs["ws_heartbeat_seconds"], 11.0)
        self.assertEqual(build.call_args.kwargs["ws_connect_timeout"], 7.0)

    def test_stop_clob_loop_processes_requires_exact_instance_provenance(self):
        stopped = []
        rows = [
            {"pid": 100, "name": "pythonw.exe", "command_line": "pythonw.exe -m weather.market.market_microstructure loop --market all", "creation_time_token": "win32-filetime:100"},
            {"pid": 101, "name": "pythonw.exe", "command_line": "pythonw.exe -m weather.market.market_microstructure loop --market all", "creation_time_token": "win32-filetime:101"},
            {"pid": 102, "name": "pythonw.exe", "command_line": "pythonw.exe -m weather.market.market_microstructure ensure --market all"},
        ]

        unproven = stop_clob_loop_processes(
            process_rows=rows,
            keep_pids={101},
            terminate_fn=lambda pid: stopped.append(pid) or {"pid": pid, "stopped": True},
        )
        supplied_provenance = stop_clob_loop_processes(
            process_rows=rows,
            keep_pids={101},
            terminate_fn=lambda pid: stopped.append(pid) or {"pid": pid, "stopped": True},
            expected_command=["pythonw.exe", "-m", "weather.market.market_microstructure", "loop", "--market", "all"],
            managed_process={
                "pid": 100,
                "expected_command": ["pythonw.exe", "-m", "weather.market.market_microstructure", "loop", "--market", "all"],
                "creation_time_token": "win32-filetime:100",
            },
        )

        self.assertEqual(unproven["stopped_count"], 0)
        self.assertEqual(supplied_provenance["stopped_count"], 0)
        self.assertEqual(stopped, [])
        self.assertEqual(supplied_provenance["matched_process_count"], 2)
        self.assertEqual(supplied_provenance["kept_pids"], [101])

    def test_stop_clob_loop_accepts_venv_resolution_before_lock_cleanup(self):
        now = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)
        status_payload = {
            "pid": 4321,
            "market_id": "all",
            "last_heartbeat": now.isoformat(),
            "interval_seconds": 60.0,
            "consecutive_errors": 0,
        }
        command = mm._clob_loop_command_from_status(status_payload)
        identity = {
            "pid": 4321,
            "expected_command": command,
            "creation_time_token": "win32-filetime:100",
        }
        status_payload["managed_process"] = identity
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "clob_loop_status.json"
            status_path.write_text(json.dumps(status_payload), encoding="utf-8")
            lock_path = root / ".clob_loop_status.json.writer.lock"
            lock_path.write_text(
                json.dumps({"pid": 4321, "managed_process": identity}),
                encoding="utf-8",
            )
            with patch.object(mm, "CLOB_LOOP_STATUS_PATH", status_path), \
                    patch.object(mm, "CLOB_DIAGNOSTICS_PATH", root / "diagnostics.jsonl"), \
                    patch.object(mm, "running_clob_loop_processes", return_value=[]), \
                    patch("weather.operations.supervisor.observe_process", return_value={
                        "state": "running",
                        "pid": 4321,
                        "argv": observed_runtime_command(command),
                        "command_line": "managed CLOB command",
                        "creation_time_token": "win32-filetime:100",
                        "inspectable": True,
                    }), \
                    patch.object(mm, "terminate_managed_process", return_value={
                        "pid": 4321,
                        "stopped": True,
                        "exited": True,
                        "reason": "verified_process_exited",
                        "termination_scope": "verified_process_handle",
                    }):
                result = mm.stop_clob_loop(now=now)

        self.assertTrue(result["stopped"])
        self.assertTrue(result["writer_lock"]["removed"])
        self.assertFalse(lock_path.exists())

    def test_stop_clob_loop_rejects_reused_pid_command_mismatch_and_unknown_identity(self):
        now = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)
        base_status = {
            "pid": 4321,
            "market_id": "all",
            "last_heartbeat": now.isoformat(),
            "interval_seconds": 60.0,
            "consecutive_errors": 0,
        }
        command = mm._clob_loop_command_from_status(base_status)
        identity = {
            "pid": 4321,
            "expected_command": command,
            "creation_time_token": "win32-filetime:100",
        }
        cases = (
            (
                "reused_pid_process_instance_mismatch",
                {"state": "running", "pid": 4321, "argv": observed_runtime_command(command), "creation_time_token": "win32-filetime:200", "inspectable": True},
            ),
            (
                "managed_process_command_mismatch",
                {"state": "running", "pid": 4321, "argv": [*observed_runtime_command(command)[:-1], "21.0"], "creation_time_token": "win32-filetime:100", "inspectable": True},
            ),
            (
                "live_process_identity_uninspectable",
                {"state": "unknown", "pid": 4321},
            ),
        )
        for expected_reason, observation in cases:
            with self.subTest(expected_reason=expected_reason), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                status_path = root / "clob_loop_status.json"
                status_path.write_text(
                    json.dumps({**base_status, "managed_process": identity}),
                    encoding="utf-8",
                )
                lock_path = root / ".clob_loop_status.json.writer.lock"
                lock_path.write_text(
                    json.dumps({"pid": 4321, "managed_process": identity}),
                    encoding="utf-8",
                )
                with patch.object(mm, "CLOB_LOOP_STATUS_PATH", status_path), \
                        patch.object(mm, "running_clob_loop_processes", return_value=[]), \
                        patch("weather.operations.supervisor.observe_process", return_value=observation), \
                        patch.object(mm, "terminate_managed_process") as terminate:
                    result = mm.stop_clob_loop(now=now)

                self.assertFalse(result["stopped"])
                self.assertEqual(result["reason"], expected_reason)
                self.assertTrue(lock_path.exists())
                terminate.assert_not_called()

    def test_ensure_clob_live_lock_mismatch_blocks_kill_and_replacement(self):
        now = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)
        status_payload = {
            "pid": 4321,
            "market_id": "all",
            "last_heartbeat": now.isoformat(),
            "interval_seconds": 60.0,
            "consecutive_errors": 0,
            "last_market_results": {"toronto": {"books": 1, "captured_tokens": 2}},
        }
        command = mm._clob_loop_command_from_status(status_payload)
        status_payload["managed_process"] = {
            "pid": 4321,
            "expected_command": command,
            "creation_time_token": "win32-filetime:100",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "clob_loop_status.json"
            status_path.write_text(json.dumps(status_payload), encoding="utf-8")
            lock_path = root / ".clob_loop_status.json.writer.lock"
            lock_path.write_text(json.dumps({"pid": 9999}), encoding="utf-8")
            with patch.object(mm, "CLOB_LOOP_STATUS_PATH", status_path), \
                    patch.object(mm, "CLOB_DIAGNOSTICS_PATH", root / "diagnostics.jsonl"), \
                    patch.object(mm, "CLOB_LOOP_CONSOLE_LOG_PATH", root / "console.log"), \
                    patch.object(mm, "CLOB_PAUSE_FLAG_PATH", root / "pause.flag"), \
                    patch.object(mm, "CLOB_SUPERVISOR_LOCK_PATH", root / "supervisor.lock"), \
                    patch.object(mm, "acquire_clob_supervisor_lock", return_value=object()), \
                    patch.object(mm, "release_clob_supervisor_lock"), \
                    patch.object(mm, "pid_is_python", return_value=True), \
                    patch.object(mm, "running_clob_loop_processes", return_value=[]), \
                    patch.object(mm, "clob_runtime_matches_current", return_value=True), \
                    patch.object(mm, "supervisor_recovery_guard", return_value={"allowed": True}), \
                    patch("weather.operations.supervisor.observe_process", return_value={
                        "state": "running",
                        "pid": 9999,
                        "inspectable": False,
                    }), \
                    patch.object(mm, "terminate_managed_process") as terminate, \
                    patch.object(mm, "start_clob_loop_detached") as start:
                result = mm.ensure_clob_loop(now=now)
                lock_still_exists = lock_path.exists()

        self.assertEqual(result["action"], "restart_blocked")
        self.assertEqual(result["reason"], "mismatched_writer_lock_owner_is_authoritative")
        self.assertEqual(result["ensure_status"], "BLOCKED")
        terminate.assert_not_called()
        start.assert_not_called()
        self.assertTrue(lock_still_exists)

    def test_ensure_clob_restarts_when_managed_instance_is_already_gone(self):
        now = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)
        already_gone = {
            "stopped": False,
            "reason": "managed_process_not_running",
            "authorization": {"process_gone": True},
        }
        status_payload = {
            "pid": 4321,
            "market_id": "all",
            "last_heartbeat": now.isoformat(),
            "interval_seconds": 60.0,
            "consecutive_errors": 0,
            "last_market_results": {"toronto": {"books": 1, "captured_tokens": 2}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "clob_loop_status.json"
            status_path.write_text(json.dumps(status_payload), encoding="utf-8")
            with patch.object(mm, "CLOB_LOOP_STATUS_PATH", status_path), \
                    patch.object(mm, "CLOB_DIAGNOSTICS_PATH", root / "diagnostics.jsonl"), \
                    patch.object(mm, "CLOB_LOOP_CONSOLE_LOG_PATH", root / "console.log"), \
                    patch.object(mm, "CLOB_PAUSE_FLAG_PATH", root / "pause.flag"), \
                    patch.object(mm, "CLOB_SUPERVISOR_LOCK_PATH", root / "supervisor.lock"), \
                    patch.object(mm, "acquire_clob_supervisor_lock", return_value=object()), \
                    patch.object(mm, "release_clob_supervisor_lock"), \
                    patch.object(mm, "pid_is_python", return_value=True), \
                    patch.object(mm, "running_clob_loop_processes", return_value=[]), \
                    patch.object(mm, "clob_runtime_matches_current", return_value=True), \
                    patch.object(mm, "clob_ensure_decision", return_value="restart"), \
                    patch.object(mm, "supervisor_recovery_guard", return_value={"allowed": True}), \
                    patch.object(mm, "loop_file_offsets", return_value={}), \
                    patch.object(mm, "quarantine_malformed_loop_lines", return_value={}), \
                    patch.object(mm, "stop_clob_loop", return_value=already_gone), \
                    patch.object(mm, "start_clob_loop_detached", return_value={"started": True}) as start:
                result = mm.ensure_clob_loop(now=now)

        self.assertEqual(result["action"], "restart")
        self.assertEqual(result["stop"], already_gone)
        start.assert_called_once()

    def test_clob_restart_cli_does_not_start_after_blocked_stop(self):
        blocked = {
            "stopped": False,
            "reason": "managed_process_provenance_missing_or_mismatched",
            "authorization": {"process_gone": False},
        }
        with patch.object(mm, "acquire_clob_supervisor_lock", return_value=object()), \
                patch.object(mm, "release_clob_supervisor_lock"), \
                patch.object(mm, "stop_clob_loop", return_value=blocked), \
                patch.object(mm, "start_clob_loop_detached") as start, \
                patch.object(sys, "argv", ["market_microstructure", "restart"]), \
                patch("builtins.print"):
            mm.main()

        start.assert_not_called()

    def test_run_book_loop_is_raw_only_and_writes_isolation_status(self):
        now = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)

        def capture_fn(**kwargs):
            self.assertEqual(kwargs["market_id"], "toronto")
            self.assertEqual(kwargs["target_date"], "2026-06-27")
            self.assertFalse(kwargs["include_price_history"])
            self.assertFalse(kwargs["include_ws_events"])
            self.assertFalse(kwargs["include_clob_features"])
            return {
                "toronto": {
                    "event_slug": "highest-temperature-in-toronto-on-june-27-2026",
                    "target_date": "2026-06-27",
                    "books": 2,
                    "captured_at_utc": now.isoformat(),
                    "raw_books_captured_at_utc": now.isoformat(),
                    "derived_features_captured_at_utc": None,
                    "include_clob_features": False,
                    "captured_tokens": 2,
                    "levels": 8,
                    "price_history_rows": 0,
                    "ws_messages": 0,
                    "midpoint_by_token": {"yes-token": 0.45},
                }
            }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.object(mm, "CLOB_LOOP_STATUS_PATH", tmp_path / "clob_loop_status.json"), \
                    patch.object(mm, "CLOB_DIAGNOSTICS_PATH", tmp_path / "clob_diagnostics.jsonl"), \
                    patch.object(mm, "CLOB_PAUSE_FLAG_PATH", tmp_path / "clob_loop_pause.flag"):
                status = run_book_loop(
                    market_id="toronto",
                    target_date="2026-06-27",
                    interval_seconds=60,
                    fast_interval_seconds=15,
                    max_iterations=1,
                    capture_fn=capture_fn,
                    sleep_fn=lambda seconds: None,
                    now_fn=lambda: now,
                )
                written = json.loads((tmp_path / "clob_loop_status.json").read_text(encoding="utf-8"))
                diagnostics = (tmp_path / "clob_diagnostics.jsonl").read_text(encoding="utf-8").splitlines()

        self.assertEqual(status["iterations"], 1)
        self.assertEqual(written["target_date"], "2026-06-27")
        self.assertEqual(written["date_selection"], "fixed_target_date")
        self.assertEqual(
            written["last_market_results"]["toronto"]["event_slug"],
            "highest-temperature-in-toronto-on-june-27-2026",
        )
        self.assertEqual(written["last_market_results"]["toronto"]["target_date"], "2026-06-27")
        self.assertEqual(written["last_market_results"]["toronto"]["books"], 2)
        self.assertEqual(written["last_market_results"]["toronto"]["price_history_rows"], 0)
        self.assertEqual(written["last_market_results"]["toronto"]["ws_messages"], 0)
        self.assertFalse(written["include_price_history"])
        self.assertFalse(written["include_ws_events"])
        self.assertEqual(written["capture_mode"], "raw_books")
        self.assertTrue(written["critical_loop_enrichment_isolated"])
        self.assertEqual(written["last_mode"], "baseline")
        self.assertEqual(written["last_books_captured_at"], now.isoformat())
        self.assertEqual(written["last_raw_books_captured_at"], now.isoformat())
        self.assertEqual(written["last_raw_books_by_market"], {"toronto": now.isoformat()})
        self.assertEqual(written["raw_book_useful_iterations"], 1)
        self.assertNotIn("last_derived_features_captured_at", written)
        self.assertNotIn("last_derived_features_by_market", written)
        self.assertEqual(written["derived_feature_error_markets"], [])
        self.assertEqual(written["last_iteration_elapsed_seconds"], 0.0)
        self.assertEqual(written["recent_iteration_elapsed_seconds"], [0.0])
        self.assertEqual(written["max_iteration_elapsed_seconds"], 0.0)
        self.assertEqual(written["max_recent_iteration_elapsed_seconds"], 0.0)
        self.assertEqual(written["last_raw_capture_contract"]["mode"], "raw_books")
        self.assertTrue(written["last_raw_capture_contract"]["injected_capture"])
        self.assertEqual(written["status_writer"]["loop"], "clob_capture")
        self.assertEqual(written["status_writer"]["pid"], os.getpid())
        self.assertEqual(len(diagnostics), 1)

    def test_default_near_close_loop_uses_parallel_raw_deadline_contract(self):
        now = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)
        raw_payload = {
            "schema_version": "clob_raw_book_refresh_v0.1",
            "mode": "raw_books",
            "market_count": 1,
            "max_workers": 12,
            "per_market_timeout_seconds": 20.0,
            "freshness_sla_seconds": 30.0,
            "fleet_elapsed_seconds": 20.1,
            "inside_freshness_sla": True,
            "ok": True,
            "summary": {"ok_market_count": 1},
            "markets": [{
                "market_id": "toronto",
                "event_slug": "highest-temperature-in-toronto-on-june-12-2026",
                "target_date": "2026-06-12",
                "books": 2,
                "captured_at_utc": now.isoformat(),
                "raw_books_captured_at_utc": now.isoformat(),
                "midpoint_by_token": {"yes-token": 0.45},
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(mm, "CLOB_LOOP_STATUS_PATH", root / "clob_loop_status.json"), \
                    patch.object(mm, "CLOB_DIAGNOSTICS_PATH", root / "clob_diagnostics.jsonl"), \
                    patch.object(mm, "CLOB_PAUSE_FLAG_PATH", root / "clob_loop_pause.flag"), \
                    patch.object(mm, "should_use_fast_interval", return_value=True), \
                    patch.object(mm, "capture_fleet_books_parallel", return_value=raw_payload) as capture:
                status = run_book_loop(
                    market_id="toronto",
                    max_iterations=1,
                    sleep_fn=lambda _seconds: None,
                    now_fn=lambda: now,
                )

        kwargs = capture.call_args.kwargs
        self.assertEqual(kwargs["freshness_sla_seconds"], 30.0)
        self.assertEqual(kwargs["per_market_timeout_seconds"], 20.0)
        self.assertEqual(kwargs["max_workers"], 12)
        self.assertFalse(kwargs.get("include_price_history", False))
        self.assertEqual(status["last_raw_capture_contract"]["fleet_elapsed_seconds"], 20.1)
        self.assertFalse(status["raw_freshness_sla_breach"])

    def test_run_book_loop_blocks_duplicate_status_writer(self):
        now = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            status_path = tmp_path / "clob_loop_status.json"
            lock = acquire_writer_lock(status_path, owner={"loop": "existing"})
            try:
                with patch.object(mm, "CLOB_LOOP_STATUS_PATH", status_path), \
                        patch.object(mm, "CLOB_DIAGNOSTICS_PATH", tmp_path / "clob_diagnostics.jsonl"):
                    result = run_book_loop(
                        market_id="toronto",
                        interval_seconds=60,
                        max_iterations=1,
                        capture_fn=lambda **_kwargs: {"toronto": {"books": 1}},
                        sleep_fn=lambda seconds: None,
                        now_fn=lambda: now,
                    )
                    diagnostics = (tmp_path / "clob_diagnostics.jsonl").read_text(encoding="utf-8")
            finally:
                release_writer_lock(lock)

        self.assertEqual(result["status"], "duplicate_writer_blocked")
        self.assertIn("duplicate_writer_blocked", diagnostics)

    def test_raw_loop_rejects_mixed_enrichment_configuration_before_capture(self):
        capture_called = False

        def capture_fn(**_kwargs):
            nonlocal capture_called
            capture_called = True
            return {}

        with self.assertRaisesRegex(ValueError, "raw-book-only"):
            run_book_loop(
                market_id="toronto",
                include_price_history=True,
                include_ws_events=False,
                max_iterations=1,
                capture_fn=capture_fn,
            )

        self.assertFalse(capture_called)

    def test_enrichment_loop_has_independent_status_and_per_market_failure(self):
        now = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)

        def capture_fn(**kwargs):
            results = {
                "toronto": {
                    "mode": "research_enrichment",
                    "status": "PASS",
                    "market_id": "toronto",
                    "price_history_rows": 2,
                    "raw_book_tape_touched": False,
                },
                "nyc": {
                    "mode": "research_enrichment",
                    "status": "DEGRADED",
                    "market_id": "nyc",
                    "error": "RuntimeError: history failed",
                    "price_history_rows": 0,
                    "raw_book_tape_touched": False,
                },
            }
            for market, result in results.items():
                kwargs["progress_callback"](market, result)
            return results

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(mm, "CLOB_ENRICHMENT_STATUS_PATH", root / "clob_enrichment_status.json"), \
                    patch.object(mm, "CLOB_ENRICHMENT_DIAGNOSTICS_PATH", root / "clob_enrichment_diagnostics.jsonl"), \
                    patch.object(mm, "CLOB_ENRICHMENT_PAUSE_FLAG_PATH", root / "clob_enrichment_pause.flag"), \
                    patch.object(mm, "CLOB_LOOP_STATUS_PATH", root / "raw_status_must_not_exist.json"):
                status = run_enrichment_loop(
                    market_id="all",
                    interval_seconds=900,
                    max_iterations=1,
                    capture_fn=capture_fn,
                    sleep_fn=lambda _seconds: None,
                    now_fn=lambda: now,
                )
                saved = json.loads(
                    (root / "clob_enrichment_status.json").read_text(encoding="utf-8")
                )
                raw_status_exists = (root / "raw_status_must_not_exist.json").exists()

        self.assertEqual(status["error_markets"], ["nyc"])
        self.assertEqual(saved["mode"], "research_enrichment")
        self.assertFalse(saved["counts_toward_raw_book_freshness"])
        self.assertFalse(saved["blocks_raw_book_capture"])
        self.assertEqual(saved["schema_version"], "clob_enrichment_loop_status_v0.1")
        self.assertIn("runtime_identity", saved)
        self.assertFalse(raw_status_exists)
        self.assertEqual(
            clob_enrichment_health(saved, now=now)["state"],
            "DEGRADED",
        )

    def test_health_marks_legacy_mixed_loop_degraded(self):
        now = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)
        status = {
            "pid": 123,
            "started_at": now.isoformat(),
            "last_heartbeat": now.isoformat(),
            "last_books_captured_at": now.isoformat(),
            "last_raw_books_captured_at": now.isoformat(),
            "interval_seconds": 60,
            "include_price_history": True,
            "include_ws_events": True,
            "last_market_results": {
                "toronto": {"captured_tokens": 2, "books": 2},
            },
        }

        health = clob_loop_health(status, now=now)

        self.assertEqual(health["state"], "DEGRADED")
        self.assertFalse(health["critical_loop_enrichment_isolated"])
        self.assertEqual(
            health["isolation_blocker"],
            "price_history_or_websocket_enabled_in_latency_critical_loop",
        )

    def _write_summary_tape(self, root, times):
        path = Path(root) / "order_books_summary.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["captured_at_utc", "clob_token_id"])
            writer.writeheader()
            for stamp in times:
                # Two tokens per capture: distinct timestamps must dedupe.
                writer.writerow({"captured_at_utc": stamp.isoformat(), "clob_token_id": "yes"})
                writer.writerow({"captured_at_utc": stamp.isoformat(), "clob_token_id": "no"})
        return path

    def test_audit_book_tape_clean_cadence_is_ok(self):
        base = datetime(2026, 6, 13, 1, 0, tzinfo=timezone.utc)
        times = [base + timedelta(seconds=60 * index) for index in range(10)]
        with tempfile.TemporaryDirectory() as tmp:
            self._write_summary_tape(tmp, times)
            result = audit_book_tape(tmp, now=times[-1] + timedelta(seconds=30))

        self.assertTrue(result["ok"])
        self.assertEqual(result["captures"], 10)
        self.assertEqual(result["median_gap_seconds"], 60.0)
        self.assertEqual(result["max_gap_seconds"], 60.0)
        self.assertEqual(result["gaps_over_threshold"], 0)
        self.assertEqual(result["trailing_age_seconds"], 30.0)

    def test_audit_book_tape_flags_internal_gap_and_stale_tail(self):
        base = datetime(2026, 6, 13, 1, 0, tzinfo=timezone.utc)
        times = [base, base + timedelta(seconds=60), base + timedelta(seconds=400)]
        with tempfile.TemporaryDirectory() as tmp:
            self._write_summary_tape(tmp, times)
            gappy = audit_book_tape(tmp, now=times[-1] + timedelta(seconds=10))
            stale = audit_book_tape(tmp, now=times[-1] + timedelta(seconds=500), max_gap_seconds=400)

        self.assertFalse(gappy["ok"])
        self.assertEqual(gappy["gaps_over_threshold"], 1)
        self.assertEqual(gappy["max_gap_seconds"], 340.0)
        self.assertIn("gaps over", gappy["reason"])
        self.assertFalse(stale["ok"])
        self.assertIn("old", stale["reason"])

    def test_audit_book_tape_ignores_startup_gap_before_cutoff(self):
        base = datetime(2026, 6, 13, 1, 0, tzinfo=timezone.utc)
        times = [base, base + timedelta(seconds=60), base + timedelta(seconds=400)]
        with tempfile.TemporaryDirectory() as tmp:
            self._write_summary_tape(tmp, times)
            result = audit_book_tape(
                tmp,
                now=times[-1] + timedelta(seconds=10),
                ignore_gaps_before=times[-1] + timedelta(seconds=1),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["gaps_over_threshold"], 0)
        self.assertEqual(result["startup_gaps_ignored"], 1)
        self.assertEqual(result["max_startup_gap_seconds"], 340.0)
        self.assertIn("ignored 1 startup gaps", result["reason"])

    def test_audit_book_tape_counts_gap_after_startup_cutoff(self):
        base = datetime(2026, 6, 13, 1, 0, tzinfo=timezone.utc)
        times = [base, base + timedelta(seconds=60), base + timedelta(seconds=400)]
        with tempfile.TemporaryDirectory() as tmp:
            self._write_summary_tape(tmp, times)
            result = audit_book_tape(
                tmp,
                now=times[-1] + timedelta(seconds=10),
                ignore_gaps_before=times[1] + timedelta(seconds=1),
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["gaps_over_threshold"], 1)
        self.assertEqual(result["startup_gaps_ignored"], 0)
        self.assertEqual(result["max_counted_gap_seconds"], 340.0)

    def test_audit_book_tape_clamps_concurrent_future_tail(self):
        base = datetime(2026, 6, 13, 1, 0, tzinfo=timezone.utc)
        times = [base, base + timedelta(seconds=60)]
        with tempfile.TemporaryDirectory() as tmp:
            self._write_summary_tape(tmp, times)
            result = audit_book_tape(tmp, now=base + timedelta(seconds=55))

        self.assertTrue(result["ok"])
        self.assertEqual(result["trailing_age_seconds"], 0.0)

    def test_fleet_effective_book_gap_uses_measured_loop_cycle(self):
        status = {
            "last_iteration_elapsed_seconds": 135.0,
            "last_sleep_seconds": 15.0,
        }

        self.assertEqual(fleet_effective_book_gap_seconds(120.0, status), 210.0)
        self.assertEqual(fleet_effective_book_gap_seconds(240.0, status), 240.0)

    def test_fleet_effective_book_gap_uses_recent_max_cycle(self):
        status = {
            "last_iteration_elapsed_seconds": 160.0,
            "recent_iteration_elapsed_seconds": [150.0, 170.0, 190.0],
            "max_recent_iteration_elapsed_seconds": 190.0,
            "last_sleep_seconds": 15.0,
        }

        self.assertEqual(fleet_effective_book_gap_seconds(120.0, status), 265.0)

    def test_fleet_effective_book_gap_uses_persisted_max_cycle(self):
        status = {
            "last_iteration_elapsed_seconds": 130.0,
            "recent_iteration_elapsed_seconds": [120.0, 150.0],
            "max_iteration_elapsed_seconds": 225.0,
            "max_recent_iteration_elapsed_seconds": 150.0,
            "last_sleep_seconds": 15.0,
        }

        self.assertEqual(fleet_effective_book_gap_seconds(120.0, status), 300.0)

    def test_audit_book_tape_missing_tape(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = audit_book_tape(tmp)

        self.assertFalse(result["ok"])
        self.assertEqual(result["captures"], 0)
        self.assertEqual(result["reason"], "no book captures")

    def test_audit_book_tape_tolerates_legacy_degree_byte(self):
        now = datetime(2026, 6, 16, 13, 40, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "order_books_summary.csv"
            path.write_bytes(
                b"captured_at_utc,range_label,clob_token_id\n"
                b"2026-06-16T13:39:30+00:00,\xb0F,yes-token\n"
            )

            result = audit_book_tape(tmp, now=now)

        self.assertTrue(result["ok"])
        self.assertEqual(result["captures"], 1)

    def test_fleet_book_audit_resolves_active_day_folders(self):
        now = datetime(2026, 6, 12, 18, 0, tzinfo=timezone.utc)
        times = [now - timedelta(seconds=90), now - timedelta(seconds=30)]
        with tempfile.TemporaryDirectory() as tmp:
            config = config_for_date(now.astimezone(mm.spec_for_id("toronto").tz).date(), "toronto")
            folder = Path(tmp) / config.event_slug
            folder.mkdir(parents=True)
            self._write_summary_tape(folder, times)
            result = fleet_book_audit(market_id="toronto", snapshots_root=tmp, now=now)

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["markets"]), 1)
        row = result["markets"][0]
        self.assertEqual(row["market_id"], "toronto")
        self.assertEqual(row["event_slug"], config.event_slug)
        self.assertTrue(row["ok"])

    def test_fleet_book_audit_can_use_explicit_target_date_before_local_midnight(self):
        now = datetime(2026, 6, 27, 4, 30, tzinfo=timezone.utc)
        times = [now - timedelta(seconds=90), now - timedelta(seconds=30)]
        with tempfile.TemporaryDirectory() as tmp:
            config = config_for_date("2026-06-27", "austin")
            folder = Path(tmp) / config.event_slug
            folder.mkdir(parents=True)
            self._write_summary_tape(folder, times)
            result = fleet_book_audit(
                market_id="austin",
                snapshots_root=tmp,
                now=now,
                target_date="2026-06-27",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["markets"][0]["event_slug"], "highest-temperature-in-austin-on-june-27-2026")

    def test_fleet_book_audit_missing_folder_not_ok(self):
        now = datetime(2026, 6, 12, 18, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            result = fleet_book_audit(market_id="toronto", snapshots_root=tmp, now=now)

        self.assertFalse(result["ok"])
        self.assertEqual(result["markets"][0]["reason"], "no book captures")

    def test_clob_diagnostic_writer_rotates_to_timestamped_siblings_without_deleting(self):
        now = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clob_diagnostics.jsonl"
            path.write_text("legacy-diagnostics\n", encoding="utf-8")
            with patch.object(mm, "CLOB_SIDECAR_ROTATE_BYTES", 1), \
                    patch.object(mm, "utc_now", return_value=now):
                mm.append_clob_diagnostic({"event": "first"}, path=path)
                mm.append_clob_diagnostic({"event": "second"}, path=path)

            rotated = sorted(Path(tmp).glob("clob_diagnostics.20260612T150000000000Z*.jsonl"))
            rotated_text = [item.read_text(encoding="utf-8") for item in rotated]
            active = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(mm.CLOB_SIDECAR_ROTATE_BYTES, 64 * 1024 * 1024)
        self.assertEqual(len(rotated), 2)
        self.assertIn("legacy-diagnostics\n", rotated_text)
        self.assertIn('{"event": "first"}\n', rotated_text)
        self.assertEqual(active["event"], "second")

    def test_start_clob_loop_rotates_console_before_opening_child_handle(self):
        now = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            console_path = tmp_path / "clob_loop_console.log"
            console_path.write_text("legacy-console\n", encoding="utf-8")

            def fake_popen(command, cwd=None, stdout=None, stderr=None, creationflags=0):
                self.assertEqual(stdout.tell(), 0)
                self.assertIs(stdout, stderr)
                stdout.write("new-child-console\n")
                stdout.flush()
                return FakeProcess()

            with patch.object(mm, "CLOB_LOOP_STATUS_PATH", tmp_path / "clob_loop_status.json"), \
                    patch.object(mm, "CLOB_DIAGNOSTICS_PATH", tmp_path / "clob_diagnostics.jsonl"), \
                    patch.object(mm, "CLOB_LOOP_CONSOLE_LOG_PATH", console_path), \
                    patch.object(mm, "CLOB_SIDECAR_ROTATE_BYTES", 1), \
                    patch.object(mm.subprocess, "Popen", fake_popen):
                result = start_clob_loop_detached(now=now)

            rotated = list(tmp_path.glob("clob_loop_console.20260612T150000000000Z*.log"))
            rotated_text = rotated[0].read_text(encoding="utf-8") if rotated else None
            active_text = console_path.read_text(encoding="utf-8")
            rotated_path = str(rotated[0]) if rotated else None

        self.assertTrue(result["started"])
        self.assertEqual(len(rotated), 1)
        self.assertEqual(rotated_text, "legacy-console\n")
        self.assertEqual(active_text, "new-child-console\n")
        self.assertEqual(result["console_log_rotated_to"], rotated_path)

    def test_start_clob_loop_detached_writes_provisional_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            calls = {}

            def fake_popen(command, cwd=None, stdout=None, stderr=None, creationflags=0):
                calls["command"] = command
                calls["cwd"] = cwd
                return FakeProcess()

            with patch.object(mm, "CLOB_LOOP_STATUS_PATH", tmp_path / "clob_loop_status.json"), \
                    patch.object(mm, "CLOB_DIAGNOSTICS_PATH", tmp_path / "clob_diagnostics.jsonl"), \
                    patch.object(mm, "CLOB_LOOP_CONSOLE_LOG_PATH", tmp_path / "clob_loop_console.log"), \
                    patch.object(mm.subprocess, "Popen", fake_popen):
                result = start_clob_loop_detached(
                    market_id="toronto",
                    target_date="2026-06-27",
                    interval_seconds=30,
                    fast_interval_seconds=10,
                    include_price_history=False,
                    include_ws_events=False,
                    ws_seconds=1.5,
                    ws_message_limit=7,
                    now=datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc),
                )
                status = json.loads((tmp_path / "clob_loop_status.json").read_text(encoding="utf-8"))
                diagnostic = json.loads(
                    (tmp_path / "clob_diagnostics.jsonl").read_text(encoding="utf-8").splitlines()[-1]
                )

        self.assertTrue(result["started"])
        self.assertEqual(status["pid"], 4321)
        self.assertEqual(status["market_id"], "toronto")
        self.assertEqual(status["target_date"], "2026-06-27")
        self.assertEqual(status["date_selection"], "fixed_target_date")
        self.assertFalse(status["include_price_history"])
        self.assertFalse(status["include_ws_events"])
        self.assertIn("weather.market.market_microstructure", calls["command"])
        self.assertIn("loop", calls["command"])
        self.assertIn("--date", calls["command"])
        self.assertIn("2026-06-27", calls["command"])
        self.assertIn("--interval-seconds", calls["command"])
        self.assertNotIn("--price-history", calls["command"])
        self.assertNotIn("--no-price-history", calls["command"])
        self.assertNotIn("--websocket-events", calls["command"])
        self.assertNotIn("--no-websocket-events", calls["command"])
        self.assertEqual(diagnostic["supervisor"], "start")
        self.assertEqual(diagnostic["market_id"], "toronto")
        self.assertEqual(diagnostic["target_date"], "2026-06-27")
        self.assertEqual(diagnostic["date_selection"], "fixed_target_date")
        self.assertEqual(diagnostic["interval_seconds"], 30)
        self.assertEqual(diagnostic["fast_interval_seconds"], 10)
        self.assertFalse(diagnostic["include_price_history"])
        self.assertFalse(diagnostic["include_ws_events"])
        self.assertEqual(diagnostic["websocket_seconds"], 1.5)
        self.assertEqual(diagnostic["websocket_message_limit"], 7)

    def test_start_clob_loop_detached_removes_dead_writer_lock_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            lock_path = tmp_path / ".clob_loop_status.json.writer.lock"
            lock_path.write_text(json.dumps({"pid": 9999}), encoding="utf-8")

            def fake_popen(command, cwd=None, stdout=None, stderr=None, creationflags=0):
                return FakeProcess()

            with patch.object(mm, "CLOB_LOOP_STATUS_PATH", tmp_path / "clob_loop_status.json"), \
                    patch.object(mm, "CLOB_DIAGNOSTICS_PATH", tmp_path / "clob_diagnostics.jsonl"), \
                    patch.object(mm, "CLOB_LOOP_CONSOLE_LOG_PATH", tmp_path / "clob_loop_console.log"), \
                    patch("weather.operations.supervisor.observe_process", return_value={"state": "not_found", "pid": 9999}), \
                    patch.object(mm.subprocess, "Popen", fake_popen):
                result = start_clob_loop_detached(
                    market_id="toronto",
                    interval_seconds=30,
                    fast_interval_seconds=10,
                    now=datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc),
                )

        self.assertTrue(result["started"])
        self.assertTrue(result["writer_lock"]["removed"])
        self.assertFalse(lock_path.exists())

    def test_start_clob_loop_detached_does_not_fight_live_writer_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            lock_path = tmp_path / ".clob_loop_status.json.writer.lock"
            lock_path.write_text(json.dumps({"pid": 9999}), encoding="utf-8")

            def fail_popen(*args, **kwargs):
                raise AssertionError("Popen should not be called while another CLOB writer is live")

            with patch.object(mm, "CLOB_LOOP_STATUS_PATH", tmp_path / "clob_loop_status.json"), \
                    patch.object(mm, "CLOB_DIAGNOSTICS_PATH", tmp_path / "clob_diagnostics.jsonl"), \
                    patch.object(mm, "CLOB_LOOP_CONSOLE_LOG_PATH", tmp_path / "clob_loop_console.log"), \
                    patch("weather.operations.supervisor.observe_process", return_value={"state": "running", "pid": 9999}), \
                    patch.object(mm.subprocess, "Popen", fail_popen):
                result = start_clob_loop_detached(
                    market_id="toronto",
                    interval_seconds=30,
                    fast_interval_seconds=10,
                    now=datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc),
                )
                lock_still_exists = lock_path.exists()

        self.assertFalse(result["started"])
        self.assertEqual(result["reason"], "writer_lock_owner_not_proven_dead")
        self.assertTrue(lock_still_exists)

    def test_start_clob_loop_detached_fails_closed_when_writer_owner_is_uninspectable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock_path = root / ".clob_loop_status.json.writer.lock"
            lock_path.write_text(json.dumps({"pid": 9999}), encoding="utf-8")
            with patch.object(mm, "CLOB_LOOP_STATUS_PATH", root / "clob_loop_status.json"), \
                    patch.object(mm, "CLOB_DIAGNOSTICS_PATH", root / "diagnostics.jsonl"), \
                    patch("weather.operations.supervisor.observe_process", return_value={"state": "unknown", "pid": 9999}), \
                    patch.object(mm.subprocess, "Popen") as popen:
                result = start_clob_loop_detached(now=datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc))
                lock_still_exists = lock_path.exists()

        self.assertFalse(result["started"])
        self.assertEqual(result["reason"], "writer_lock_owner_not_proven_dead")
        self.assertTrue(lock_still_exists)
        popen.assert_not_called()

    def test_clob_cleanup_retains_same_pid_replacement_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "clob_loop_status.json"
            lock_path = root / ".clob_loop_status.json.writer.lock"
            lock_path.write_text(json.dumps({
                "pid": 4321,
                "managed_process": {"pid": 4321, "creation_time_token": "win32-filetime:new"},
            }), encoding="utf-8")
            with patch.object(mm, "CLOB_LOOP_STATUS_PATH", status_path):
                result = mm._cleanup_clob_writer_lock(
                    expected_pid=4321,
                    confirmed_exit={"exited": True},
                    exited_identity={"pid": 4321, "creation_time_token": "win32-filetime:old"},
                )
                lock_still_exists = lock_path.exists()

        self.assertFalse(result["removed"])
        self.assertEqual(result["reason"], "writer_lock_process_instance_mismatch")
        self.assertTrue(lock_still_exists)


if __name__ == "__main__":
    unittest.main()
