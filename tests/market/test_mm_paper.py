import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from mm_paper import build_known_edge_map, build_paper_payload, write_outputs


EVENT = "highest-temperature-in-atlanta-on-june-14-2026"
TARGET_DATE = "2026-06-14"


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_promotion(path):
    payload = {
        "decisions": {
            "verdict": "PARTIAL_PASS",
            "action_counts": {
                "PROMOTE_CANDIDATE": 1,
                "KEEP_SHADOW": 1,
                "BLOCK_CANDIDATE": 1,
            },
            "markets": [
                {
                    "market_id": "atlanta",
                    "action": "PROMOTE_CANDIDATE",
                    "verdict": "PASS",
                    "metrics": {
                        "candidate_brier": 0.03,
                        "market_brier": 0.04,
                        "delta_vs_market": -0.01,
                    },
                },
                {
                    "market_id": "chicago",
                    "action": "KEEP_SHADOW",
                    "verdict": "SHADOW",
                    "metrics": {
                        "candidate_brier": 0.05,
                        "market_brier": 0.04,
                        "delta_vs_market": 0.01,
                    },
                },
                {
                    "market_id": "san-francisco",
                    "action": "BLOCK_CANDIDATE",
                    "verdict": "BLOCK",
                    "metrics": {
                        "candidate_brier": 0.06,
                        "market_brier": 0.04,
                        "delta_vs_market": 0.02,
                    },
                },
            ],
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_casebook(path):
    payload = {
        "cases": [
            {
                "case_id": "case-atlanta-80",
                "event_slug": EVENT,
                "market_id": "atlanta",
                "range_label": "80-81 F",
                "start_time_utc": "2026-06-14T16:00:00+00:00",
                "end_time_utc": "2026-06-14T16:05:00+00:00",
                "taxonomy": "market_lead",
            }
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_run_fixture(root):
    runs_root = root / "mm_runs"
    run_folder = runs_root / TARGET_DATE / "paper-run"
    run_folder.mkdir(parents=True)
    run_config = {
        "run_id": "paper-run",
        "mode": "paper-live-forward",
        "target_date": TARGET_DATE,
        "policy_hash": "locked-policy",
    }
    (run_folder / "run_config.json").write_text(json.dumps(run_config), encoding="utf-8")
    quote_row = {
        "run_id": "paper-run",
        "target_date": TARGET_DATE,
        "run_mode": "paper-live-forward",
        "generated_at_utc": "2026-06-14T16:00:00+00:00",
        "captured_at_utc": "2026-06-14T15:59:30+00:00",
        "policy_hash": "locked-policy",
        "quote_permission": "True",
        "market_id": "atlanta",
        "event_slug": EVENT,
        "range_label": "80-81 F",
        "bin_kind": "eq",
        "bin_value": "80",
        "bin_value_hi": "81",
        "clob_token_id": "token-80",
        "fair_probability": "0.50",
        "market_mid": "0.50",
        "bid_price": "0.49",
        "bid_size": "5",
        "ask_price": "0.51",
        "ask_size": "5",
        "regime": "harvest",
        "source_fresh": "True",
        "book_imbalance_1pct": "0.10",
        "min_order_size": "1",
        "reason_code": "QUOTE_HARVEST_MID",
    }
    write_csv(run_folder / "quote_intents_long.csv", list(quote_row.keys()), [quote_row])
    return runs_root, run_folder


def write_snapshot_fixture(root):
    snapshots_root = root / "snapshots"
    folder = snapshots_root / EVENT
    folder.mkdir(parents=True)
    trades = [
        {
            "trade_time_utc": "2026-06-14T16:00:10+00:00",
            "clob_token_id": "token-80",
            "price": "0.49",
            "size": "10",
            "side": "SELL",
        },
        {
            "trade_time_utc": "2026-06-14T16:00:20+00:00",
            "clob_token_id": "token-80",
            "price": "0.48",
            "size": "3",
            "side": "SELL",
        },
        {
            "trade_time_utc": "2026-06-14T16:00:30+00:00",
            "clob_token_id": "token-80",
            "price": "0.47",
            "size": "",
            "side": "SELL",
        },
    ]
    write_csv(folder / "trades_long.csv", list(trades[0].keys()), trades)
    book_rows = [
        {
            "captured_at_utc": "2026-06-14T15:59:50+00:00",
            "event_slug": EVENT,
            "market_id": "atlanta",
            "range_label": "80-81 F",
            "bin_kind": "eq",
            "bin_value": "80",
            "bin_value_hi": "81",
            "clob_token_id": "token-80",
            "best_bid": "0.49",
            "best_ask": "0.51",
            "midpoint": "0.50",
            "last_trade_price": "",
            "bid_size_at_best": "10",
            "ask_size_at_best": "10",
            "bid_depth_1pct": "10",
            "ask_depth_1pct": "10",
            "tick_size": "0.001",
        },
        {
            "captured_at_utc": "2026-06-14T16:00:15+00:00",
            "event_slug": EVENT,
            "market_id": "atlanta",
            "range_label": "80-81 F",
            "bin_kind": "eq",
            "bin_value": "80",
            "bin_value_hi": "81",
            "clob_token_id": "token-80",
            "best_bid": "0.49",
            "best_ask": "0.51",
            "midpoint": "0.50",
            "last_trade_price": "",
            "bid_size_at_best": "5",
            "ask_size_at_best": "10",
            "bid_depth_1pct": "5",
            "ask_depth_1pct": "10",
            "tick_size": "0.001",
        },
        {
            "captured_at_utc": "2026-06-14T16:00:25+00:00",
            "event_slug": EVENT,
            "market_id": "atlanta",
            "range_label": "80-81 F",
            "bin_kind": "eq",
            "bin_value": "80",
            "bin_value_hi": "81",
            "clob_token_id": "token-80",
            "best_bid": "0.48",
            "best_ask": "0.51",
            "midpoint": "0.505",
            "last_trade_price": "",
            "bid_size_at_best": "5",
            "ask_size_at_best": "10",
            "bid_depth_1pct": "5",
            "ask_depth_1pct": "10",
            "tick_size": "0.001",
        },
    ]
    write_csv(folder / "order_books_summary.csv", list(book_rows[0].keys()), book_rows)
    marks = [
        {
            "point_time_utc": "2026-06-14T16:00:50+00:00",
            "clob_token_id": "token-80",
            "price": "0.53",
        },
        {
            "point_time_utc": "2026-06-14T16:01:20+00:00",
            "clob_token_id": "token-80",
            "price": "0.53",
        },
        {
            "point_time_utc": "2026-06-14T16:05:30+00:00",
            "clob_token_id": "token-80",
            "price": "0.54",
        },
        {
            "point_time_utc": "2026-06-14T16:30:30+00:00",
            "clob_token_id": "token-80",
            "price": "0.54",
        },
    ]
    write_csv(folder / "price_history.csv", list(marks[0].keys()), marks)
    settlement = {
        "event_slug": EVENT,
        "market_id": "atlanta",
        "settlement_bucket": 80,
        "winning_band": "80-81 F",
        "quality_grade": "complete",
    }
    (folder / "settlement.json").write_text(json.dumps(settlement), encoding="utf-8")
    return snapshots_root


class TestMMPaper(unittest.TestCase):
    def test_conservative_fills_queue_markouts_incentives_and_known_edge_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root, run_folder = write_run_fixture(root)
            snapshots_root = write_snapshot_fixture(root)
            backtest_root = root / "backtest"
            promotion = backtest_root / "promotion.json"
            casebook = backtest_root / "casebook.json"
            write_promotion(promotion)
            write_casebook(casebook)

            config = {
                "quote_ttl_seconds": 120.0,
                "reward_campaign_pool_usdc": 100.0,
                "reward_competitor_q": 50.0,
                "reward_min_payout_usdc": 0.0,
            }
            payload = build_paper_payload(
                runs_root=runs_root,
                snapshots_root=snapshots_root,
                backtest_root=backtest_root,
                run_folders=[run_folder],
                casebook_path=casebook,
                promotion_refresh=promotion,
                config=config,
                now="2026-06-14T17:00:00+00:00",
            )
            payload, known_edge = write_outputs(
                payload,
                json_out=backtest_root / "mm_paper_report.json",
                report_out=backtest_root / "mm_paper_report.md",
                fills_out=backtest_root / "mm_paper_fills_long.csv",
                known_edge_out=backtest_root / "mm_known_edge_map.json",
                known_edge_report_out=backtest_root / "mm_known_edge_map.md",
                promotion_refresh=promotion,
            )

            self.assertEqual(payload["summary"]["conservative_fills"], 1)
            self.assertEqual(payload["summary"]["trade_evidence_gaps"]["missing_size_trade_rows"], 1)
            fill = payload["fills"][0]
            self.assertEqual(fill["side"], "YES_BID")
            self.assertEqual(float(fill["fill_price"]), 0.49)
            self.assertEqual(float(fill["fill_size"]), 3.0)
            self.assertEqual(float(fill["through_trade_price"]), 0.48)
            self.assertGreater(float(fill["markout_30m_per_share"]), 0.0)
            self.assertEqual(float(fill["settlement_outcome"]), 1.0)
            self.assertEqual(fill["casebook_taxonomy"], "market_lead")
            self.assertGreater(float(fill["maker_rebate_estimate_usdc"]), 0.0)
            self.assertGreater(float(fill["liquidity_reward_estimate_usdc"]), 0.0)
            self.assertGreater(float(fill["flattening_fee_estimate_usdc"]), 0.0)
            self.assertGreater(float(fill["net_pnl_after_fees_incentives_usdc"]), 0.0)

            bid_queue = [row for row in payload["queue_companion"] if row["leg_id"].endswith("YES_BID")][0]
            self.assertEqual(bid_queue["status"], "estimated_full_fill")
            self.assertEqual(float(bid_queue["estimated_fill_size"]), 5.0)

            files = payload["outputs"]
            self.assertTrue(Path(files["json"]).exists())
            self.assertTrue(Path(files["report"]).exists())
            self.assertTrue(Path(files["fills_csv"]).exists())
            self.assertTrue(Path(files["known_edge_json"]).exists())
            csv_rows = read_csv(files["fills_csv"])
            self.assertEqual(len(csv_rows), 1)

            permissions = {(row["market_id"], row["permission"]) for row in known_edge["records"]}
            self.assertIn(("atlanta", "edge_research"), permissions)
            self.assertIn(("chicago", "harvest_only"), permissions)
            self.assertIn(("san-francisco", "no_quote"), permissions)

    def test_no_runs_writes_empty_report_and_fail_closed_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest_root = root / "backtest"
            promotion = backtest_root / "promotion.json"
            write_promotion(promotion)

            payload = build_paper_payload(
                runs_root=root / "missing_mm_runs",
                snapshots_root=root / "snapshots",
                backtest_root=backtest_root,
                promotion_refresh=promotion,
                config={"quote_ttl_seconds": 120.0},
                now="2026-06-14T17:00:00+00:00",
            )
            known_edge = build_known_edge_map(payload, promotion_refresh=promotion)

            self.assertEqual(payload["summary"]["quote_rows"], 0)
            self.assertEqual(payload["summary"]["conservative_fills"], 0)
            permission_by_market = {row["market_id"]: row["permission"] for row in known_edge["records"]}
            self.assertEqual(permission_by_market["atlanta"], "harvest_only")
            self.assertEqual(permission_by_market["chicago"], "harvest_only")
            self.assertEqual(permission_by_market["san-francisco"], "no_quote")


if __name__ == "__main__":
    unittest.main()
