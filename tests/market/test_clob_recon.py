import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path
from weather.market.clob_recon import build_recon_payload, policy_overrides_from_recon, write_outputs


EVENT = "highest-temperature-in-atlanta-on-june-14-2026"


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_recon_fixture(root):
    folder = root / "snapshots" / EVENT
    folder.mkdir(parents=True)
    rows = []
    for minute, bid, ask, bid_depth, ask_depth in [
        (0, "0.49", "0.51", "120", "100"),
        (1, "0.48", "0.52", "60", "80"),
    ]:
        rows.append({
            "captured_at_utc": f"2026-06-14T15:{minute:02d}:00+00:00",
            "event_slug": EVENT,
            "market_id": "atlanta",
            "range_label": "80-81 F",
            "bin_kind": "eq",
            "bin_value": "80",
            "bin_value_hi": "81",
            "outcome": "yes",
            "clob_token_id": "token-80",
            "min_order_size": "5",
            "tick_size": "0.001",
            "best_bid": bid,
            "best_ask": ask,
            "spread": str(float(ask) - float(bid)),
            "midpoint": "0.50",
            "bid_size_at_best": "20",
            "ask_size_at_best": "20",
            "bid_depth_1pct": bid_depth,
            "ask_depth_1pct": ask_depth,
            "bid_depth_5pct": bid_depth,
            "ask_depth_5pct": ask_depth,
            "bid_depth_all": bid_depth,
            "ask_depth_all": ask_depth,
            "sell_vwap_10": bid,
            "sell_fillable_10": "10",
            "buy_vwap_10": ask,
            "buy_fillable_10": "10",
            "sell_vwap_100": bid,
            "sell_fillable_100": bid_depth,
            "buy_vwap_100": ask,
            "buy_fillable_100": ask_depth,
        })
    write_csv(folder / "order_books_summary.csv", list(rows[0].keys()), rows)
    trades = [{
        "received_at_utc": "2026-06-14T15:00:10+00:00",
        "event_slug": EVENT,
        "market_id": "atlanta",
        "asset_id": "token-80",
        "price": "0.49",
        "side": "SELL",
    }]
    write_csv(folder / "market_ws_events.csv", list(trades[0].keys()), trades)
    return folder


class TestClobRecon(unittest.TestCase):
    def test_build_recon_payload_scores_reward_depth_and_passive_markout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = write_recon_fixture(root)

            payload = build_recon_payload(
                snapshots_root=root / "snapshots",
                folders=[folder],
                config={"executable_sizes": [10], "toxicity_horizons_seconds": [30, 300]},
                now="2026-06-14T16:00:00+00:00",
            )

            self.assertEqual(payload["summary"]["book_rows"], 2)
            self.assertEqual(payload["summary"]["slice_rows"], 2)
            self.assertEqual(payload["summary"]["passive_trade_markout_rows"], 1)
            bid_slice = [row for row in payload["slices"] if row["side"] == "YES_BID"][0]
            self.assertGreater(float(bid_slice["mean_reward_qualifying_size"]), 0.0)
            self.assertGreater(float(bid_slice["mean_passive_markout_30s"]), 0.0)
            self.assertIn("quote_size", payload["policy_parameter_suggestions"])

    def test_recon_outputs_and_policy_overrides_are_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = write_recon_fixture(root)
            payload = build_recon_payload(root / "snapshots", folders=[folder], now="2026-06-14T16:00:00+00:00")
            payload = write_outputs(
                payload,
                json_out=root / "clob_book_recon.json",
                report_out=root / "clob_book_recon.md",
                slices_out=root / "clob_book_recon_slices.csv",
            )
            overrides, diag = policy_overrides_from_recon(root / "clob_book_recon.json", enabled=True)

            self.assertTrue(Path(payload["outputs"]["json"]).exists())
            self.assertTrue(Path(payload["outputs"]["report"]).exists())
            self.assertTrue(Path(payload["outputs"]["slices_csv"]).exists())
            self.assertTrue(diag["exists"])
            self.assertIn("quote_size", overrides)


if __name__ == "__main__":
    unittest.main()
