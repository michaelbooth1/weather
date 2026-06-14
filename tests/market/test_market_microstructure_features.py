import csv
import json
import os
import tempfile
import unittest
from pathlib import Path

sys_path = os.path.abspath("src")
if sys_path not in os.sys.path:
    os.sys.path.insert(0, sys_path)

from market_microstructure_features import (  # noqa: E402
    clob_feature_rows_for_folder,
    feature_index_for_folder,
)


class TestMarketMicrostructureFeatures(unittest.TestCase):
    def _write_csv(self, path, fieldnames, rows):
        with Path(path).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_clob_feature_rows_join_latest_nonfuture_book(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_csv(
                root / "snapshots_long.csv",
                [
                    "snapshot_id",
                    "captured_at_utc",
                    "event_slug",
                    "range_label",
                    "bin_kind",
                    "bin_value_c",
                    "bin_value_hi",
                    "model_probability",
                    "market_yes",
                ],
                [
                    {
                        "snapshot_id": "s1",
                        "captured_at_utc": "2026-06-13T12:00:00+00:00",
                        "event_slug": "highest-temperature-in-nyc-on-june-13-2026",
                        "range_label": "80-81 F",
                        "bin_kind": "eq",
                        "bin_value_c": "80",
                        "bin_value_hi": "",
                        "model_probability": "0.60",
                        "market_yes": "0.42",
                    },
                    {
                        "snapshot_id": "stale",
                        "captured_at_utc": "2026-06-13T12:10:00+00:00",
                        "event_slug": "highest-temperature-in-nyc-on-june-13-2026",
                        "range_label": "80-81 F",
                        "bin_kind": "eq",
                        "bin_value_c": "80",
                        "bin_value_hi": "",
                        "model_probability": "0.60",
                        "market_yes": "0.42",
                    },
                ],
            )
            book_fields = [
                "captured_at_utc",
                "event_slug",
                "market_id",
                "range_label",
                "bin_kind",
                "bin_value",
                "bin_value_hi",
                "outcome",
                "clob_token_id",
                "best_bid",
                "best_ask",
                "spread",
                "midpoint",
                "bid_depth_1pct",
                "ask_depth_1pct",
                "bid_depth_5pct",
                "ask_depth_5pct",
                "bid_depth_all",
                "ask_depth_all",
                "imbalance_1pct",
                "imbalance_5pct",
            ]

            def book_row(stamp, midpoint):
                return {
                    "captured_at_utc": stamp,
                    "event_slug": "highest-temperature-in-nyc-on-june-13-2026",
                    "market_id": "nyc",
                    "range_label": "80-81 F",
                    "bin_kind": "eq",
                    "bin_value": "80",
                    "bin_value_hi": "81",
                    "outcome": "Yes",
                    "clob_token_id": "yes-token",
                    "best_bid": "0.44",
                    "best_ask": "0.46",
                    "spread": "0.02",
                    "midpoint": str(midpoint),
                    "bid_depth_1pct": "10",
                    "ask_depth_1pct": "15",
                    "bid_depth_5pct": "20",
                    "ask_depth_5pct": "30",
                    "bid_depth_all": "100",
                    "ask_depth_all": "200",
                    "imbalance_1pct": "-0.2",
                    "imbalance_5pct": "-0.1",
                }

            self._write_csv(
                root / "order_books_summary.csv",
                book_fields,
                [
                    book_row("2026-06-13T11:54:00+00:00", 0.30),
                    book_row("2026-06-13T11:58:00+00:00", 0.35),
                    book_row("2026-06-13T11:59:00+00:00", 0.40),
                    book_row("2026-06-13T11:59:30+00:00", 0.40),
                ],
            )
            self._write_csv(
                root / "price_history.csv",
                [
                    "captured_at_utc",
                    "event_slug",
                    "market_id",
                    "range_label",
                    "outcome",
                    "clob_token_id",
                    "point_time_utc",
                    "price",
                ],
                [
                    {
                        "captured_at_utc": "2026-06-13T12:00:00+00:00",
                        "event_slug": "highest-temperature-in-nyc-on-june-13-2026",
                        "market_id": "nyc",
                        "range_label": "80-81 F",
                        "outcome": "Yes",
                        "clob_token_id": "yes-token",
                        "point_time_utc": "2026-06-13T11:54:00+00:00",
                        "price": "0.37",
                    },
                    {
                        "captured_at_utc": "2026-06-13T12:00:00+00:00",
                        "event_slug": "highest-temperature-in-nyc-on-june-13-2026",
                        "market_id": "nyc",
                        "range_label": "80-81 F",
                        "outcome": "Yes",
                        "clob_token_id": "yes-token",
                        "point_time_utc": "2026-06-13T11:58:00+00:00",
                        "price": "0.38",
                    },
                    {
                        "captured_at_utc": "2026-06-13T12:00:00+00:00",
                        "event_slug": "highest-temperature-in-nyc-on-june-13-2026",
                        "market_id": "nyc",
                        "range_label": "80-81 F",
                        "outcome": "Yes",
                        "clob_token_id": "yes-token",
                        "point_time_utc": "2026-06-13T11:59:00+00:00",
                        "price": "0.41",
                    },
                ],
            )
            with (root / "market_ws.jsonl").open("w", encoding="utf-8") as handle:
                for received_at, price in [
                    ("2026-06-13T11:58:40+00:00", "0.38"),
                    ("2026-06-13T11:59:10+00:00", "0.39"),
                    ("2026-06-13T11:59:50+00:00", "0.43"),
                ]:
                    handle.write(json.dumps({
                        "received_at_utc": received_at,
                        "event_slug": "highest-temperature-in-nyc-on-june-13-2026",
                        "market_id": "nyc",
                        "payload": {
                            "event_type": "price_change",
                            "market": "0xabc",
                            "price_changes": [
                                {
                                    "asset_id": "yes-token",
                                    "price": price,
                                    "side": "BUY",
                                }
                            ],
                        },
                    }) + "\n")

            rows = clob_feature_rows_for_folder(root, market_id="nyc")
            index = feature_index_for_folder(root, market_id="nyc")

        fresh = next(row for row in rows if row["snapshot_id"] == "s1")
        stale = next(row for row in rows if row["snapshot_id"] == "stale")

        self.assertEqual(fresh["market_id"], "nyc")
        self.assertEqual(fresh["clob_token_id"], "yes-token")
        self.assertEqual(fresh["clob_feature_available"], 1.0)
        self.assertEqual(fresh["clob_book_age_seconds"], 30.0)
        self.assertAlmostEqual(fresh["clob_midpoint"], 0.40)
        self.assertAlmostEqual(fresh["clob_best_bid"], 0.44)
        self.assertAlmostEqual(fresh["clob_best_ask"], 0.46)
        self.assertAlmostEqual(fresh["clob_depth_1pct_total"], 25.0)
        self.assertAlmostEqual(fresh["clob_depth_5pct_total"], 50.0)
        self.assertAlmostEqual(fresh["clob_depth_all_total"], 300.0)
        self.assertAlmostEqual(fresh["clob_midpoint_change_60s"], 0.05)
        self.assertAlmostEqual(fresh["clob_midpoint_change_300s"], 0.10)
        self.assertAlmostEqual(fresh["clob_midpoint_stickiness_seconds"], 30.0)
        self.assertEqual(fresh["clob_price_history_available"], 1.0)
        self.assertEqual(fresh["clob_price_history_age_seconds"], 60.0)
        self.assertAlmostEqual(fresh["clob_price_history_price"], 0.41)
        self.assertAlmostEqual(fresh["clob_price_history_change_60s"], 0.03)
        self.assertAlmostEqual(fresh["clob_price_history_change_300s"], 0.04)
        self.assertEqual(fresh["clob_price_history_points_300s"], 2.0)
        self.assertEqual(fresh["clob_ws_event_count_60s"], 2.0)
        self.assertEqual(fresh["clob_ws_event_count_300s"], 3.0)
        self.assertEqual(fresh["clob_ws_last_age_seconds"], 10.0)
        self.assertAlmostEqual(fresh["clob_ws_last_price"], 0.43)
        self.assertAlmostEqual(fresh["clob_ws_price_change_60s"], 0.05)
        self.assertAlmostEqual(fresh["clob_model_edge_to_midpoint"], 0.20)
        self.assertAlmostEqual(fresh["clob_model_edge_to_price_history"], 0.19)
        self.assertAlmostEqual(fresh["clob_market_yes_minus_midpoint"], 0.02)
        self.assertEqual(stale["clob_feature_available"], 0.0)
        self.assertIn(("nyc", "s1", "eq", 80, 81), index)


if __name__ == "__main__":
    unittest.main()
