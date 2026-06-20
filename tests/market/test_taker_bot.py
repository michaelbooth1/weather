import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.market.taker_bot import build_run_once


EVENT = "highest-temperature-in-atlanta-on-june-14-2026"
TARGET_DATE = "2026-06-14"
NOW = "2026-06-14T16:00:00+00:00"


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_market_fixture(
    root,
    settled=True,
    missing_token=False,
    blank_tokens=False,
    captured_at="2026-06-14T15:59:30+00:00",
    book_captured_at="2026-06-14T15:59:50+00:00",
    bands=None,
    duplicate_first_snapshot=False,
):
    snapshots_root = root / "snapshots"
    folder = snapshots_root / EVENT
    folder.mkdir(parents=True)
    snapshot_rows = []
    clob_rows = []
    book_rows = []
    token_rows = []
    bands = bands or [(80, "0.70", "0.60"), (82, "0.52", "0.51")]
    for value, fair, ask in bands:
        token = "" if blank_tokens or (missing_token and value == 80) else f"token-{value}"
        condition = "" if blank_tokens else f"condition-{value}"
        label = f"{value}-{value + 1} F"
        snapshot_rows.append({
            "snapshot_id": "s1",
            "captured_at_utc": captured_at,
            "event_slug": EVENT,
            "model_version": "candidate",
            "range_label": label,
            "condition_id": condition,
            "clob_yes_token_id": token,
            "bin_kind": "eq",
            "bin_value_c": str(value),
            "model_probability": fair,
            "market_yes": "0.50",
            "market_status": "active",
        })
        clob_rows.append({
            "snapshot_id": "s1",
            "captured_at_utc": captured_at,
            "event_slug": EVENT,
            "market_id": "atlanta",
            "range_label": label,
            "bin_kind": "eq",
            "bin_value": str(value),
            "bin_value_hi": str(value + 1),
            "clob_token_id": token,
            "clob_book_captured_at_utc": book_captured_at,
            "clob_book_age_seconds": "10",
            "clob_midpoint": "0.55",
            "clob_best_bid": "0.50",
            "clob_best_ask": ask,
            "clob_depth_1pct_total": "100",
        })
        book_rows.append({
            "captured_at_utc": book_captured_at,
            "event_slug": EVENT,
            "market_id": "atlanta",
            "range_label": label,
            "bin_kind": "eq",
            "bin_value": str(value),
            "bin_value_hi": str(value + 1),
            "condition_id": condition,
            "clob_token_id": token,
            "outcome": "yes",
            "best_bid": "0.50",
            "best_ask": ask,
            "midpoint": "0.55",
            "ask_size_at_best": "40",
            "bid_size_at_best": "40",
            "ask_depth_1pct": "40",
            "bid_depth_1pct": "40",
            "min_order_size": "1",
            "tick_size": "0.001",
        })
        token_rows.append({
            "event_slug": EVENT,
            "market_id": "atlanta",
            "condition_id": condition,
            "range_label": label,
            "bin_kind": "eq",
            "bin_value": str(value),
            "bin_value_hi": str(value + 1),
            "outcome": "yes",
            "clob_token_id": token,
            "active": "true",
            "closed": "false",
        })
    if duplicate_first_snapshot and snapshot_rows:
        snapshot_rows.append(dict(snapshot_rows[0]))
    write_csv(folder / "snapshots_long.csv", list(snapshot_rows[0].keys()), snapshot_rows)
    write_csv(folder / "clob_features_long.csv", list(clob_rows[0].keys()), clob_rows)
    write_csv(folder / "order_books_summary.csv", list(book_rows[0].keys()), book_rows)
    write_csv(folder / "clob_tokens.csv", list(token_rows[0].keys()), token_rows)
    source_row = {
        "snapshot_id": "s1",
        "captured_at_utc": captured_at,
        "event_slug": EVENT,
        "model_version": "candidate",
        "source": "wu_current",
        "ok": "true",
        "status": "fresh",
        "stale": "false",
        "fetched_at": captured_at,
    }
    write_csv(folder / "source_status_long.csv", list(source_row.keys()), [source_row])
    marks = [
        {
            "point_time_utc": "2026-06-14T16:00:30+00:00",
            "clob_token_id": "token-80",
            "price": "0.72",
        },
        {
            "point_time_utc": "2026-06-14T16:00:30+00:00",
            "clob_token_id": "token-82",
            "price": "0.50",
        },
    ]
    write_csv(folder / "price_history.csv", list(marks[0].keys()), marks)
    if settled:
        settlement = {
            "event_slug": EVENT,
            "market_id": "atlanta",
            "settlement_bucket": 80,
            "winning_band": "80-81 F",
            "quality_grade": "complete",
        }
        (folder / "settlement.json").write_text(json.dumps(settlement), encoding="utf-8")
    return snapshots_root


def write_observation_status(path, market_ledger):
    path.write_text(json.dumps({
        "last_heartbeat": "2026-06-14T15:59:50+00:00",
        "consecutive_errors": 0,
        "markets": {"atlanta": {"monotonic_high_ledger": market_ledger}},
    }), encoding="utf-8")


class TestTakerBot(unittest.TestCase):
    def test_buys_positive_edge_and_scores_settlement_pnl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(root, settled=True)

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=12,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now=NOW,
                config={"min_edge": 0.05, "max_order_usdc": 10, "max_position_per_token_usdc": 10},
            )

            self.assertEqual(payload["summary"]["latest_tick_filled_orders"], 1)
            self.assertEqual(payload["summary"]["cumulative_filled_orders"], 1)
            self.assertAlmostEqual(payload["summary"]["budget_spent_usdc"], 10.0)
            self.assertAlmostEqual(payload["summary"]["cumulative_net_pnl_usdc"], 6.666667)
            self.assertEqual(payload["tape_integrity"]["status"], "PASS")
            self.assertEqual(
                payload["summary"]["tape_integrity"]["actual_rows"],
                payload["summary"]["cumulative_order_rows"],
            )
            orders = read_csv(Path(payload["orders_path"]))
            filled = [row for row in orders if row["order_status"] == "FILLED"]
            self.assertEqual(len(filled), 1)
            self.assertEqual(filled[0]["clob_token_id"], "token-80")
            self.assertEqual(filled[0]["pnl_source"], "settlement")
            self.assertAlmostEqual(float(filled[0]["fill_price"]), 0.60)
            self.assertAlmostEqual(float(filled[0]["settlement_outcome"]), 1.0)
            self.assertTrue(Path(payload["daily_pnl_path"]).exists())
            self.assertTrue(Path(payload["run_report_path"]).exists())
            self.assertIn("Tape integrity", Path(payload["run_report_path"]).read_text(encoding="utf-8"))

    def test_append_does_not_duplicate_unchanged_opportunity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(root, settled=True)
            common = {
                "target_date": TARGET_DATE,
                "budget_usdc": 12,
                "markets": "atlanta",
                "runs_root": root / "taker_runs",
                "snapshots_root": snapshots_root,
                "run_id": "daily",
                "config": {"min_edge": 0.05, "max_order_usdc": 10, "max_position_per_token_usdc": 100},
            }
            first = build_run_once(now=NOW, **common)
            second = build_run_once(now="2026-06-14T16:01:00+00:00", **common)

            self.assertEqual(first["summary"]["cumulative_filled_orders"], 1)
            self.assertEqual(second["summary"]["latest_tick_filled_orders"], 0)
            self.assertEqual(second["summary"]["latest_tick_rows"], 0)
            self.assertEqual(second["summary"]["cumulative_filled_orders"], 1)
            self.assertAlmostEqual(second["summary"]["budget_spent_usdc"], 10.0)
            orders = read_csv(Path(second["orders_path"]))
            self.assertEqual(sum(1 for row in orders if row["order_status"] == "FILLED"), 1)

    def test_unsettled_order_uses_mark_to_market_pnl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(root, settled=False)

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=12,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now="2026-06-14T16:01:00+00:00",
                config={"min_edge": 0.05, "max_order_usdc": 10, "max_position_per_token_usdc": 10},
                ledger_root=root / "empty_settlements",
            )

            pnl = payload["pnl"]["summary"]
            self.assertEqual(pnl["settled_order_count"], 0)
            self.assertEqual(pnl["unsettled_order_count"], 1)
            self.assertAlmostEqual(pnl["mark_to_market_pnl_usdc"], 2.0)
            self.assertAlmostEqual(payload["summary"]["cumulative_net_pnl_usdc"], 2.0)

    def test_missing_clob_token_blocks_taker_buy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(root, settled=True, missing_token=True)

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=12,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now=NOW,
                config={"min_edge": 0.05, "max_order_usdc": 10, "max_position_per_token_usdc": 10},
            )

            self.assertEqual(payload["summary"]["latest_tick_filled_orders"], 0)
            orders = read_csv(Path(payload["orders_path"]))
            self.assertTrue(any(row["reason_code"] == "NO_TRADE_MISSING_TOKEN" for row in orders))

    def test_blank_clob_tokens_are_market_discovery_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(root, settled=True, blank_tokens=True)

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=12,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now=NOW,
                config={"min_edge": 0.05, "max_order_usdc": 10, "max_position_per_token_usdc": 10},
            )

        self.assertEqual(payload["summary"]["latest_tick_filled_orders"], 0)
        self.assertEqual(payload["summary"]["root_cause_class"], "blocked_by_market_discovery")
        self.assertEqual(payload["summary"]["first_failing_gate"], "clob_discovery")
        self.assertEqual(payload["markets"][0]["clob_token_discovery"]["root_cause"], "blank_clob_token_ids")
        self.assertTrue(payload["summary"]["zero_trades_expected"])

    def test_orders_include_settlement_normalized_current_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(root, settled=True)
            status_path = root / "observation_status.json"
            write_observation_status(status_path, {
                "market_id": "atlanta",
                "raw_current_high": 81.7,
                "raw_current_high_bucket": 82,
                "settlement_current_high": 82,
                "high_source": "wu_history",
                "revision_state": "current",
                "settlement_bin_key": "eq:82",
            })

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=12,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now=NOW,
                observation_status_path=status_path,
                config={"min_edge": 0.05, "max_order_usdc": 10, "max_position_per_token_usdc": 10},
            )
            orders = read_csv(Path(payload["orders_path"]))
            assessment = payload["markets"][0]["current_high_assessment"]

        self.assertEqual(assessment["settlement_current_high"], 82)
        self.assertEqual(assessment["probability_on_settlement_current_high"], 0.52)
        self.assertTrue(all(float(row["settlement_current_high"]) == 82.0 for row in orders))
        self.assertTrue(all(float(row["probability_on_settlement_current_high"]) == 0.52 for row in orders))

    def test_early_hour_blocks_guarded_current_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                captured_at="2026-06-14T09:30:00+00:00",
                book_captured_at="2026-06-14T09:30:10+00:00",
            )
            status_path = root / "observation_status.json"
            write_observation_status(status_path, {
                "market_id": "atlanta",
                "raw_current_high": 68.0,
                "raw_current_high_bucket": 68,
                "settlement_current_high": 70,
                "high_source": "wu_history",
                "revision_state": "current",
                "settlement_bin_key": "eq:70-71",
                "current_max_state": "pre_reset_current_max_null",
                "current_max_disposition": "null_before_reset",
                "current_high_trusted": False,
                "current_high_guard_reason": "pre_reset_current_max_not_validated_by_wu_history",
            })

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=12,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now="2026-06-14T09:31:00+00:00",
                observation_status_path=status_path,
                config={"min_edge": 0.05, "max_order_usdc": 10, "max_position_per_token_usdc": 10},
            )
            orders = read_csv(Path(payload["orders_path"]))

        self.assertEqual(payload["summary"]["latest_tick_filled_orders"], 0)
        self.assertTrue(any(row["reason_code"] == "NO_TRADE_EARLY_HOUR_CURRENT_HIGH_GUARDED" for row in orders))
        self.assertTrue(all(row["order_status"] != "FILLED" for row in orders))

    def test_early_hour_caps_taker_notional(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                captured_at="2026-06-14T09:30:00+00:00",
                book_captured_at="2026-06-14T09:30:10+00:00",
            )

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=12,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now="2026-06-14T09:31:00+00:00",
                config={
                    "min_edge": 0.05,
                    "max_order_usdc": 10,
                    "max_position_per_token_usdc": 10,
                    "early_hour_block_guarded_current_high": False,
                },
            )
            filled = [row for row in read_csv(Path(payload["orders_path"])) if row["order_status"] == "FILLED"]

        self.assertEqual(len(filled), 1)
        self.assertEqual(filled[0]["early_hour_guardrail_status"], "active")
        self.assertAlmostEqual(float(filled[0]["fill_notional_usdc"]), 2.0)
        self.assertAlmostEqual(payload["summary"]["budget_spent_usdc"], 2.0)

    def test_early_hour_caps_daily_position_count(self):
        bands = [(80 + index, "0.80", "0.60") for index in range(15)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                captured_at="2026-06-14T09:30:00+00:00",
                book_captured_at="2026-06-14T09:30:10+00:00",
                bands=bands,
            )

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=100,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now="2026-06-14T09:31:00+00:00",
                config={
                    "min_edge": 0.05,
                    "max_order_usdc": 10,
                    "max_position_per_token_usdc": 10,
                    "early_hour_block_guarded_current_high": False,
                    "early_hour_max_daily_positions": 3,
                    "early_hour_max_order_usdc": 1,
                    "early_hour_max_position_per_token_usdc": 1,
                },
            )
            orders = read_csv(Path(payload["orders_path"]))

        self.assertEqual(payload["summary"]["latest_tick_filled_orders"], 3)
        self.assertEqual(sum(1 for row in orders if row["reason_code"] == "NO_TRADE_EARLY_HOUR_DAILY_POSITION_LIMIT"), 12)

    def test_same_tick_duplicate_intents_are_deduped_before_budgeting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(root, settled=True, duplicate_first_snapshot=True)

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=30,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now=NOW,
                config={"min_edge": 0.05, "max_order_usdc": 10, "max_position_per_token_usdc": 100},
            )
            orders = read_csv(Path(payload["orders_path"]))
            filled = [row for row in orders if row["order_status"] == "FILLED"]

        self.assertEqual(len(filled), 1)
        self.assertEqual(len({row["intent_key"] for row in orders}), len(orders))
        self.assertEqual(payload["summary"]["latest_tick_filled_orders"], 1)


if __name__ == "__main__":
    unittest.main()
