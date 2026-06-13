import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath("src"))

import market_microstructure as mm  # noqa: E402
from market_microstructure import (  # noqa: E402
    clob_ensure_decision,
    clob_loop_health,
    capture_event_books,
    price_history_rows,
    record_market_websocket,
    run_book_loop,
    should_use_fast_interval,
    start_clob_loop_detached,
    summarize_order_book,
    token_rows_from_event,
)
from market_config import config_for_date  # noqa: E402


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


class FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, value):
        self.sent.append(value)

    def recv(self):
        return json.dumps({
            "event_type": "price_change",
            "asset_id": "yes-token",
            "market": "0xabc",
            "price": "0.46",
            "side": "BUY",
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

    def test_capture_event_books_writes_tokens_books_levels_and_history(self):
        fake = FakeClobClient()
        with tempfile.TemporaryDirectory() as tmp:
            result = capture_event_books(
                sample_event(),
                market_id="toronto",
                clob_client=fake,
                root=tmp,
                outcomes="yes",
                include_price_history=True,
                history_minutes=60,
                now=datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc),
            )
            root = Path(tmp)
            token_rows = list(csv.DictReader((root / "clob_tokens.csv").open(encoding="utf-8", newline="")))
            summary_rows = list(csv.DictReader((root / "order_books_summary.csv").open(encoding="utf-8", newline="")))
            level_rows = list(csv.DictReader((root / "order_books_long.csv").open(encoding="utf-8", newline="")))
            history_rows = list(csv.DictReader((root / "price_history.csv").open(encoding="utf-8", newline="")))

        self.assertEqual(result["captured_tokens"], 1)
        self.assertEqual(result["books"], 1)
        self.assertEqual(len(token_rows), 2)
        self.assertEqual(summary_rows[0]["clob_token_id"], "yes-token")
        self.assertEqual(len(level_rows), 4)
        self.assertEqual(history_rows[0]["price"], "0.45")
        self.assertEqual(fake.book_requests[0][0], ["yes-token"])
        self.assertEqual(fake.history_requests[0][0], "yes-token")

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
        self.assertEqual(rows[0]["event_type"], "price_change")
        self.assertEqual(rows[0]["asset_id"], "yes-token")

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
        self.assertEqual(clob_loop_health({**base, "error_markets": ["nyc"]}, now=now)["state"], "DEGRADED")
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

    def test_run_book_loop_writes_status_and_diagnostics(self):
        now = datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc)

        def capture_fn(**kwargs):
            self.assertEqual(kwargs["market_id"], "toronto")
            return {
                "toronto": {
                    "books": 2,
                    "captured_tokens": 2,
                    "levels": 8,
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
        self.assertEqual(written["last_mode"], "baseline")
        self.assertEqual(written["last_books_captured_at"], now.isoformat())
        self.assertEqual(len(diagnostics), 1)

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
        self.assertIn("src.market_microstructure", calls["command"])
        self.assertIn("loop", calls["command"])
        self.assertIn("--interval-seconds", calls["command"])


if __name__ == "__main__":
    unittest.main()
