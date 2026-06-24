import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import weather.market.market_microstructure as mm  # noqa: E402
from weather.market.market_microstructure import (  # noqa: E402
    audit_book_tape,
    clob_ensure_decision,
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
    running_clob_loop_processes,
    should_use_fast_interval,
    start_clob_loop_detached,
    stop_clob_loop_processes,
    summarize_order_book,
    token_rows_from_event,
)
from weather.market.market_microstructure_features import snapshot_band_key  # noqa: E402
from weather.market.market_config import config_for_date  # noqa: E402
from weather.operations.supervisor import acquire_writer_lock, release_writer_lock  # noqa: E402


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
        self.assertEqual(clob_loop_health({**base, "consecutive_errors": 3}, now=now)["state"], "ERRORING")
        stale = {**base, "last_heartbeat": (now - timedelta(seconds=181)).isoformat()}
        self.assertEqual(clob_loop_health(stale, now=now)["state"], "DEAD")
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
        stop_loop.assert_not_called()
        start_loop.assert_not_called()

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

    def test_stop_clob_loop_processes_stops_matching_orphans(self):
        stopped = []
        rows = [
            {"pid": 100, "name": "pythonw.exe", "command_line": "pythonw.exe -m weather.market.market_microstructure loop --market all"},
            {"pid": 101, "name": "pythonw.exe", "command_line": "pythonw.exe -m weather.market.market_microstructure loop --market all"},
            {"pid": 102, "name": "pythonw.exe", "command_line": "pythonw.exe -m weather.market.market_microstructure ensure --market all"},
        ]

        result = stop_clob_loop_processes(
            process_rows=rows,
            keep_pids={101},
            terminate_fn=lambda pid: stopped.append(pid) or {"pid": pid, "stopped": True},
        )

        self.assertEqual(stopped, [100])
        self.assertEqual(result["matched_process_count"], 2)
        self.assertEqual(result["stopped_count"], 1)
        self.assertEqual(result["kept_pids"], [101])

    def test_run_book_loop_writes_status_and_diagnostics(self):
        now = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)

        def capture_fn(**kwargs):
            self.assertEqual(kwargs["market_id"], "toronto")
            self.assertTrue(kwargs["include_price_history"])
            self.assertTrue(kwargs["include_ws_events"])
            return {
                "toronto": {
                    "books": 2,
                    "captured_at_utc": now.isoformat(),
                    "raw_books_captured_at_utc": now.isoformat(),
                    "derived_features_captured_at_utc": now.isoformat(),
                    "include_clob_features": True,
                    "captured_tokens": 2,
                    "levels": 8,
                    "price_history_rows": 4,
                    "ws_messages": 1,
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
        self.assertEqual(written["last_market_results"]["toronto"]["books"], 2)
        self.assertEqual(written["last_market_results"]["toronto"]["price_history_rows"], 4)
        self.assertEqual(written["last_market_results"]["toronto"]["ws_messages"], 1)
        self.assertTrue(written["include_price_history"])
        self.assertTrue(written["include_ws_events"])
        self.assertEqual(written["last_mode"], "baseline")
        self.assertEqual(written["last_books_captured_at"], now.isoformat())
        self.assertEqual(written["last_raw_books_captured_at"], now.isoformat())
        self.assertEqual(written["last_raw_books_by_market"], {"toronto": now.isoformat()})
        self.assertEqual(written["raw_book_useful_iterations"], 1)
        self.assertEqual(written["last_derived_features_captured_at"], now.isoformat())
        self.assertEqual(written["last_derived_features_by_market"], {"toronto": now.isoformat()})
        self.assertEqual(written["derived_feature_error_markets"], [])
        self.assertEqual(written["last_iteration_elapsed_seconds"], 0.0)
        self.assertEqual(written["recent_iteration_elapsed_seconds"], [0.0])
        self.assertEqual(written["max_iteration_elapsed_seconds"], 0.0)
        self.assertEqual(written["max_recent_iteration_elapsed_seconds"], 0.0)
        self.assertEqual(written["status_writer"]["loop"], "clob_capture")
        self.assertEqual(written["status_writer"]["pid"], os.getpid())
        self.assertEqual(len(diagnostics), 1)

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

    def test_fleet_book_audit_missing_folder_not_ok(self):
        now = datetime(2026, 6, 12, 18, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            result = fleet_book_audit(market_id="toronto", snapshots_root=tmp, now=now)

        self.assertFalse(result["ok"])
        self.assertEqual(result["markets"][0]["reason"], "no book captures")

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
                    interval_seconds=30,
                    fast_interval_seconds=10,
                    now=datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc),
                )
                status = json.loads((tmp_path / "clob_loop_status.json").read_text(encoding="utf-8"))

        self.assertTrue(result["started"])
        self.assertEqual(status["pid"], 4321)
        self.assertEqual(status["market_id"], "toronto")
        self.assertIn("weather.market.market_microstructure", calls["command"])
        self.assertIn("loop", calls["command"])
        self.assertIn("--interval-seconds", calls["command"])

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
                    patch.object(mm, "pid_is_python", return_value=False), \
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
                    patch.object(mm, "pid_is_python", return_value=True), \
                    patch.object(mm.subprocess, "Popen", fail_popen):
                result = start_clob_loop_detached(
                    market_id="toronto",
                    interval_seconds=30,
                    fast_interval_seconds=10,
                    now=datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc),
                )
                lock_still_exists = lock_path.exists()

        self.assertFalse(result["started"])
        self.assertEqual(result["reason"], "writer lock owner is still live")
        self.assertTrue(lock_still_exists)


if __name__ == "__main__":
    unittest.main()
