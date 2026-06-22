import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.market.taker_bot import (
    FINALIZATION_SCHEMA_VERSION,
    ORDER_COLUMNS,
    STRATEGY_BAKEOFF_SCHEMA_VERSION,
    build_run_once,
    finalize_taker_run,
    next_run_policy_gate,
    run_taker_strategy_bakeoff,
)


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


def order_row(
    market_id,
    event_slug,
    range_label,
    bin_value,
    bin_value_hi,
    fill_size,
    fill_notional,
    fair_probability=0.9,
    mark_pnl=None,
):
    fill_price = float(fill_notional) / float(fill_size)
    return {
        "schema_version": "taker_bot_run_v0.1",
        "policy_version": "taker_bot_policy_v0.1",
        "target_date": "2026-06-19",
        "generated_at_utc": "2026-06-20T03:40:12+00:00",
        "snapshot_id": "20260619T234000-0400",
        "captured_at_utc": "2026-06-20T03:40:00+00:00",
        "market_id": market_id,
        "event_slug": event_slug,
        "range_label": range_label,
        "bin_kind": "eq",
        "bin_value": str(bin_value),
        "bin_value_hi": str(bin_value_hi),
        "clob_token_id": f"token-{market_id}-{bin_value}",
        "order_status": "FILLED",
        "action": "BUY",
        "fair_probability": str(fair_probability),
        "best_bid": str(max(0.001, fill_price - 0.001)),
        "best_ask": str(fill_price),
        "market_mid": str(fill_price),
        "edge": str(float(fair_probability) - fill_price),
        "expected_profit_per_share": str(float(fair_probability) - fill_price),
        "ask_size_at_best": str(fill_size),
        "book_age_seconds": "10",
        "model_age_seconds": "10",
        "source_fresh": "True",
        "source_freshness_state": "all_fresh",
        "fill_size": str(fill_size),
        "fill_price": str(fill_price),
        "fill_notional_usdc": str(fill_notional),
        "total_spent_usdc": str(fill_notional),
        "fee_usdc": "0",
        "reason_code": "BUY_EDGE",
        "mark_pnl_usdc": "" if mark_pnl is None else str(mark_pnl),
        "pnl_source": "" if mark_pnl is None else "mark_to_market",
        "net_pnl_usdc": "" if mark_pnl is None else str(mark_pnl),
    }


def write_taker_run(root, run_id, rows, reported_net, reported_mtm, reported_unsettled):
    run = root / "taker_runs" / "2026-06-19" / run_id
    run.mkdir(parents=True)
    write_csv(run / "orders_long.csv", ORDER_COLUMNS, rows)
    payload = {
        "schema_version": "taker_bot_run_v0.1",
        "run_id": run_id,
        "target_date": "2026-06-19",
        "mode": "paper-taker",
        "summary": {
            "budget_usdc": 100,
            "budget_spent_usdc": 59.80507,
            "cumulative_filled_orders": len(rows),
            "cumulative_net_pnl_usdc": reported_net,
            "root_cause_class": "policy_no_edge",
        },
        "pnl": {
            "summary": {
                "budget_usdc": 100,
                "filled_order_count": len(rows),
                "net_pnl_usdc": reported_net,
                "mark_to_market_pnl_usdc": reported_mtm,
                "settled_order_count": 0,
                "unsettled_order_count": reported_unsettled,
                "reason_counts": {"BUY_EDGE": len(rows)},
            }
        },
    }
    (run / "run_summary.json").write_text(json.dumps(payload), encoding="utf-8")
    (run / "daily_pnl.json").write_text(json.dumps(payload["pnl"]), encoding="utf-8")
    return run


def write_labels(path, rows):
    fieldnames = ["event_slug", "market_id", "target_date", "settlement_bucket", "winning_band", "quality_grade"]
    write_csv(path, fieldnames, rows)


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

    def test_multi_arm_strategy_mode_shares_inputs_and_isolates_budgets(self):
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
                strategies="raw_edge_control,small_order_probe",
                experiment_id="exp-fixture",
            )

            orders = read_csv(Path(payload["orders_path"]))
            filled = [row for row in orders if row["order_status"] == "FILLED"]
            by_strategy = {row["strategy_id"]: row for row in payload["pnl"]["by_strategy"]}
            ledger_events = [
                json.loads(line)
                for line in Path(payload["budget_ledger_path"]).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            strategy_summary = json.loads(Path(payload["strategy_summary_path"]).read_text(encoding="utf-8"))
            strategy_report = Path(payload["strategy_report_path"]).read_text(encoding="utf-8")

        self.assertEqual(payload["mode"], "paper-taker-multi-arm")
        self.assertEqual(payload["summary"]["strategy_count"], 2)
        self.assertEqual({row["strategy_id"] for row in filled}, {"raw_edge_control", "small_order_probe"})
        self.assertEqual({row["experiment_id"] for row in orders}, {"exp-fixture"})
        self.assertAlmostEqual(by_strategy["raw_edge_control"]["spent_usdc"], 10.0)
        self.assertAlmostEqual(by_strategy["small_order_probe"]["spent_usdc"], 1.0)
        self.assertEqual(by_strategy["raw_edge_control"]["independent_opinion_count"], 1)
        self.assertEqual(by_strategy["small_order_probe"]["independent_opinion_count"], 1)
        self.assertEqual(strategy_summary["comparison"]["strategy_count"], 2)
        self.assertEqual(
            strategy_summary["comparison"]["countable_strategy_quality_candidate_status"],
            "COUNTABLE_SETTLED",
        )
        self.assertIn("Taker Strategy Comparison Report", strategy_report)
        self.assertEqual(
            {event["strategy_id"] for event in ledger_events if event.get("event") == "taker_buy_filled"},
            {"raw_edge_control", "small_order_probe"},
        )

    def test_calibrated_edge_uses_fractional_kelly_and_risk_adjusted_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(root, settled=True, bands=[(80, "0.70", "0.60")])
            status_path = root / "observation_status.json"
            write_observation_status(status_path, {
                "market_id": "atlanta",
                "raw_current_high": 78.0,
                "raw_current_high_bucket": 78,
                "settlement_current_high": 78,
                "high_source": "wu_history",
                "revision_state": "current",
                "settlement_bin_key": "eq:78",
                "current_high_trusted": False,
            })

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=100,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now=NOW,
                observation_status_path=status_path,
                config={"max_order_usdc": 10, "max_position_per_token_usdc": 10},
                strategies="calibrated_edge",
                experiment_id="calibrated-sizing-fixture",
            )
            filled = [row for row in read_csv(Path(payload["orders_path"])) if row["order_status"] == "FILLED"]

        self.assertEqual(len(filled), 1)
        row = filled[0]
        self.assertEqual(row["sizing_rule"], "fractional_kelly")
        self.assertEqual(row["strategy_id"], "calibrated_edge")
        self.assertIn("untrusted_current_high", row["reliability_reason"])
        self.assertLess(float(row["reliability_adjusted_fair_probability"]), float(row["fair_probability"]))
        self.assertLess(float(row["risk_adjusted_edge"]), float(row["edge"]))
        self.assertGreater(float(row["fill_notional_usdc"]), 0.0)
        self.assertLess(float(row["fill_notional_usdc"]), 10.0)
        self.assertEqual(payload["pnl"]["by_strategy"][0]["low_price_tail_fill_count"], 0)

    def test_low_price_tail_strategy_caps_tail_lottery_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(root, settled=True, bands=[(80, "0.40", "0.01")])

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=100,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now=NOW,
                config={"max_order_usdc": 10, "max_position_per_token_usdc": 10},
                strategies="low_price_tail_capped",
                experiment_id="tail-sizing-fixture",
            )
            filled = [row for row in read_csv(Path(payload["orders_path"])) if row["order_status"] == "FILLED"]
            strategy = payload["pnl"]["by_strategy"][0]

        self.assertEqual(len(filled), 1)
        row = filled[0]
        self.assertEqual(row["sizing_rule"], "tail_lottery")
        self.assertEqual(row["low_price_tail"], "True")
        self.assertEqual(row["tail_risk_bucket"], "low_price_tail")
        self.assertLessEqual(float(row["requested_notional_usdc"]), 0.5)
        self.assertLessEqual(float(row["fill_notional_usdc"]), 0.5)
        self.assertEqual(strategy["low_price_tail_fill_count"], 1)
        self.assertLessEqual(strategy["low_price_tail_spent_usdc"], 0.5)
        self.assertEqual(payload["summary"]["active_strategy_id"], "low_price_tail_capped")
        self.assertEqual(payload["summary"]["active_strategy_lifecycle"], "candidate_canary")
        self.assertEqual(payload["summary"]["active_strategy_canary"]["strategy_id"], "low_price_tail_capped")

    def test_strategy_bakeoff_replays_shared_tape_and_writes_promotion_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(root, settled=True)
            source_payload = build_run_once(
                TARGET_DATE,
                budget_usdc=12,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now=NOW,
                config={"min_edge": 0.05, "max_order_usdc": 10, "max_position_per_token_usdc": 10},
            )
            labels = root / "market_day_labels.csv"
            write_labels(labels, [
                {
                    "event_slug": EVENT,
                    "market_id": "atlanta",
                    "target_date": TARGET_DATE,
                    "settlement_bucket": 80,
                    "winning_band": "80-81 F",
                    "quality_grade": "complete",
                }
            ])
            out_json = root / "bakeoff.json"
            out_report = root / "bakeoff.md"

            bakeoff = run_taker_strategy_bakeoff(
                source_payload["run_folder"],
                labels_csv=labels,
                strategies="raw_edge_control,small_order_probe",
                budget_usdc=12,
                out_json=out_json,
                out_report=out_report,
                now="2026-06-20T12:00:00+00:00",
                experiment_id="bakeoff-fixture",
            )
            saved = json.loads(out_json.read_text(encoding="utf-8"))
            report = out_report.read_text(encoding="utf-8")
            by_strategy = {row["strategy_id"]: row for row in bakeoff["pnl"]["by_strategy"]}
            gates = {row["strategy_id"]: row for row in bakeoff["promotion_gates"]}

        self.assertEqual(bakeoff["schema_version"], STRATEGY_BAKEOFF_SCHEMA_VERSION)
        self.assertEqual(saved["schema_version"], STRATEGY_BAKEOFF_SCHEMA_VERSION)
        self.assertIn("Settlement-Scored Taker Strategy Bakeoff", report)
        self.assertEqual(bakeoff["summary"]["strategy_count"], 2)
        self.assertEqual(bakeoff["label_summary"]["label_rows"], 1)
        self.assertFalse(bakeoff["blockers"])
        self.assertAlmostEqual(by_strategy["raw_edge_control"]["spent_usdc"], 10.0)
        self.assertAlmostEqual(by_strategy["small_order_probe"]["spent_usdc"], 1.0)
        self.assertAlmostEqual(by_strategy["raw_edge_control"]["net_pnl_usdc"], 6.666667)
        self.assertAlmostEqual(by_strategy["small_order_probe"]["net_pnl_usdc"], 0.666667)
        self.assertEqual(gates["raw_edge_control"]["status"], "PASS")
        self.assertEqual(gates["small_order_probe"]["status"], "PASS")
        self.assertEqual(bakeoff["paired_comparisons"][0]["candidate_strategy_id"], "small_order_probe")
        self.assertLess(bakeoff["paired_comparisons"][0]["delta_net_pnl_usdc"], 0)

    def test_strategy_bakeoff_blocks_partial_quality_labels_from_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(root, settled=True)
            source_payload = build_run_once(
                TARGET_DATE,
                budget_usdc=12,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now=NOW,
                config={"min_edge": 0.05, "max_order_usdc": 10, "max_position_per_token_usdc": 10},
            )
            labels = root / "market_day_labels.csv"
            write_labels(labels, [
                {
                    "event_slug": EVENT,
                    "market_id": "atlanta",
                    "target_date": TARGET_DATE,
                    "settlement_bucket": 80,
                    "winning_band": "80-81 F",
                    "quality_grade": "partial",
                }
            ])

            bakeoff = run_taker_strategy_bakeoff(
                source_payload["run_folder"],
                labels_csv=labels,
                strategies="raw_edge_control",
                budget_usdc=12,
                out_json=root / "partial-bakeoff.json",
                out_report=root / "partial-bakeoff.md",
                now="2026-06-20T12:00:00+00:00",
            )

        self.assertEqual(bakeoff["label_summary"]["partial_rows"], 1)
        self.assertEqual(
            {row["code"] for row in bakeoff["blockers"]},
            {"partial_target_date_labels"},
        )
        self.assertEqual(bakeoff["promotion_gates"][0]["status"], "PASS")

    def test_low_price_tail_partial_label_stays_candidate_canary(self):
        gate = next_run_policy_gate(
            {
                "strategies": [{"strategy_id": "low_price_tail_capped", "net_pnl_usdc": 5.0}],
                "comparison": {"best_settlement_scored_strategy_id": "low_price_tail_capped"},
            },
            run_config={
                "active_strategy_id": "low_price_tail_capped",
                "active_strategy_lifecycle": "candidate_canary",
                "active_strategy_canary": {"min_settled_orders": 1, "age_days": 0},
                "policy_config": {
                    "canary_min_settled_orders": 1,
                    "canary_min_complete_label_days": 1,
                },
            },
            bakeoff={
                "label_summary": {"label_rows": 1, "complete_rows": 0, "partial_rows": 1},
                "blockers": [{"code": "partial_target_date_labels"}],
                "pnl": {
                    "by_strategy": [
                        {"strategy_id": "low_price_tail_capped", "net_pnl_usdc": 5.0}
                    ]
                },
                "promotion_gates": [
                    {
                        "strategy_id": "low_price_tail_capped",
                        "status": "PASS",
                        "settled_order_count": 1,
                        "failed_gates": [],
                    }
                ],
            },
        )

        self.assertEqual(gate["status"], "PASS")
        self.assertEqual(gate["active_strategy_lifecycle"], "candidate_canary")
        self.assertEqual(gate["active_strategy_lifecycle_status"], "candidate_canary")
        self.assertFalse(gate["promotion_eligible"])
        self.assertEqual(gate["next_action"], "continue_canary_until_complete_labels")
        self.assertEqual(gate["complete_label_sample_count"], 0)
        self.assertEqual(gate["canary_settled_order_count"], 1)

    def test_finalize_low_price_tail_partial_label_report_stays_candidate_canary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(root, settled=True, bands=[(80, "0.40", "0.01")])
            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=100,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now=NOW,
                config={
                    "canary_min_settled_orders": 1,
                    "max_order_usdc": 10,
                    "max_position_per_token_usdc": 10,
                },
                strategies="low_price_tail_capped",
                experiment_id="tail-canary-fixture",
            )
            labels = root / "market_day_labels.csv"
            write_labels(labels, [
                {
                    "event_slug": EVENT,
                    "market_id": "atlanta",
                    "target_date": TARGET_DATE,
                    "settlement_bucket": 80,
                    "winning_band": "80-81 F",
                    "quality_grade": "partial",
                }
            ])
            run_folder = Path(payload["run_folder"])
            run_taker_strategy_bakeoff(
                run_folder,
                labels_csv=labels,
                strategies="low_price_tail_capped",
                budget_usdc=100,
                out_json=run_folder / "strategy_bakeoff.json",
                out_report=run_folder / "strategy_bakeoff.md",
                now="2026-06-20T12:00:00+00:00",
            )

            finalized = finalize_taker_run(run_folder, labels_csv=labels, now="2026-06-20T12:10:00+00:00")
            report = Path(finalized["settled_report_path"]).read_text(encoding="utf-8")

        self.assertEqual(finalized["summary"]["active_strategy_id"], "low_price_tail_capped")
        self.assertEqual(finalized["summary"]["active_strategy_lifecycle"], "candidate_canary")
        self.assertEqual(finalized["summary"]["active_strategy_lifecycle_status"], "candidate_canary")
        self.assertFalse(finalized["summary"]["active_strategy_promotion_eligible"])
        self.assertEqual(
            finalized["summary"]["active_strategy_next_action"],
            "continue_canary_until_complete_labels",
        )
        self.assertIn("candidate_canary", report)
        self.assertNotIn("promoted_default", report)

    def test_low_price_tail_complete_label_promotes_after_sample(self):
        gate = next_run_policy_gate(
            {
                "strategies": [{"strategy_id": "low_price_tail_capped", "net_pnl_usdc": 5.0}],
                "comparison": {"best_settlement_scored_strategy_id": "low_price_tail_capped"},
            },
            run_config={
                "active_strategy_id": "low_price_tail_capped",
                "active_strategy_lifecycle": "candidate_canary",
                "active_strategy_canary": {"min_settled_orders": 2, "age_days": 1},
                "policy_config": {
                    "canary_min_settled_orders": 2,
                    "canary_min_complete_label_days": 1,
                },
            },
            bakeoff={
                "label_summary": {"label_rows": 1, "complete_rows": 1, "partial_rows": 0},
                "blockers": [],
                "pnl": {
                    "by_strategy": [
                        {"strategy_id": "low_price_tail_capped", "net_pnl_usdc": 5.0}
                    ]
                },
                "promotion_gates": [
                    {
                        "strategy_id": "low_price_tail_capped",
                        "status": "PASS",
                        "settled_order_count": 2,
                        "failed_gates": [],
                    }
                ],
            },
        )

        self.assertEqual(gate["status"], "PASS")
        self.assertEqual(gate["active_strategy_lifecycle_status"], "promoted_default")
        self.assertTrue(gate["promotion_eligible"])
        self.assertEqual(gate["next_action"], "promote_default")
        self.assertEqual(gate["complete_label_sample_count"], 1)
        self.assertEqual(gate["canary_settled_order_count"], 2)

    def test_low_price_tail_complete_label_blocks_failed_canary(self):
        gate = next_run_policy_gate(
            {
                "strategies": [
                    {"strategy_id": "low_price_tail_capped", "net_pnl_usdc": -2.0},
                    {"strategy_id": "small_order_probe", "net_pnl_usdc": 1.0},
                ],
                "comparison": {"best_settlement_scored_strategy_id": "small_order_probe"},
            },
            run_config={
                "active_strategy_id": "low_price_tail_capped",
                "active_strategy_lifecycle": "candidate_canary",
                "active_strategy_canary": {"min_settled_orders": 1, "age_days": 1},
                "policy_config": {
                    "canary_min_settled_orders": 1,
                    "canary_min_complete_label_days": 1,
                },
            },
            bakeoff={
                "label_summary": {"label_rows": 1, "complete_rows": 1, "partial_rows": 0},
                "blockers": [],
                "pnl": {
                    "by_strategy": [
                        {"strategy_id": "low_price_tail_capped", "net_pnl_usdc": -2.0},
                        {"strategy_id": "small_order_probe", "net_pnl_usdc": 1.0},
                    ]
                },
                "promotion_gates": [
                    {
                        "strategy_id": "low_price_tail_capped",
                        "status": "BLOCK",
                        "settled_order_count": 1,
                        "failed_gates": ["non_negative_settled_roi"],
                    },
                    {
                        "strategy_id": "small_order_probe",
                        "status": "PASS",
                        "settled_order_count": 1,
                        "failed_gates": [],
                    },
                ],
            },
        )

        self.assertEqual(gate["status"], "BLOCK")
        self.assertEqual(gate["active_strategy_lifecycle_status"], "blocked")
        self.assertFalse(gate["promotion_eligible"])
        self.assertEqual(gate["next_action"], "rollback_to_small_order_probe")
        self.assertIn("non_negative_settled_roi", gate["canary_failed_gates"])

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

    def test_finalize_taker_run_scores_june_19_labels_without_mutating_orders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                order_row(
                    "miami",
                    "highest-temperature-in-miami-on-june-19-2026",
                    "92-93 F",
                    92,
                    93,
                    14.705882,
                    10.0,
                ),
                order_row(
                    "nyc",
                    "highest-temperature-in-new-york-city-on-june-19-2026",
                    "86-87 F",
                    86,
                    87,
                    1.0,
                    18.0746,
                ),
                order_row(
                    "atlanta",
                    "highest-temperature-in-atlanta-on-june-19-2026",
                    "88-89 F",
                    88,
                    89,
                    54.76,
                    11.73047,
                ),
                order_row(
                    "toronto",
                    "highest-temperature-in-toronto-on-june-19-2026",
                    "22 C",
                    22,
                    22,
                    27.027027,
                    20.0,
                ),
            ]
            run = write_taker_run(
                root,
                "taker-20260619-221a357c",
                rows,
                reported_net=-17.208695,
                reported_mtm=-17.208695,
                reported_unsettled=50,
            )
            labels = root / "market_day_labels.csv"
            write_labels(labels, [
                {
                    "event_slug": "highest-temperature-in-miami-on-june-19-2026",
                    "market_id": "miami",
                    "target_date": "2026-06-19",
                    "settlement_bucket": 92,
                    "winning_band": "92-93 F",
                    "quality_grade": "complete",
                },
                {
                    "event_slug": "highest-temperature-in-new-york-city-on-june-19-2026",
                    "market_id": "nyc",
                    "target_date": "2026-06-19",
                    "settlement_bucket": 82,
                    "winning_band": "82-83 F",
                    "quality_grade": "complete",
                },
                {
                    "event_slug": "highest-temperature-in-atlanta-on-june-19-2026",
                    "market_id": "atlanta",
                    "target_date": "2026-06-19",
                    "settlement_bucket": 88,
                    "winning_band": "88-89 F",
                    "quality_grade": "complete",
                },
                {
                    "event_slug": "highest-temperature-in-toronto-on-june-19-2026",
                    "market_id": "toronto",
                    "target_date": "2026-06-19",
                    "settlement_bucket": 22,
                    "winning_band": "22 C",
                    "quality_grade": "complete",
                },
            ])
            raw_before = (run / "orders_long.csv").read_text(encoding="utf-8")

            finalized = finalize_taker_run(run, labels_csv=labels, now="2026-06-20T12:00:00+00:00")

            self.assertEqual((run / "orders_long.csv").read_text(encoding="utf-8"), raw_before)
            self.assertEqual(finalized["schema_version"], FINALIZATION_SCHEMA_VERSION)
            self.assertTrue((run / "settled_orders_long.csv").exists())
            self.assertTrue((run / "settled_pnl.json").exists())
            self.assertTrue((run / "settled_report.md").exists())
            summary = finalized["summary"]
            self.assertEqual(summary["settled_order_count"], 4)
            self.assertEqual(summary["unsettled_order_count"], 0)
            self.assertEqual(summary["pnl_source"], "settlement_finalization")
            self.assertAlmostEqual(summary["settlement_pnl_usdc"], 36.687839)
            self.assertAlmostEqual(summary["net_pnl_usdc"], 36.687839)
            self.assertEqual(finalized["reconciliation"]["status"], "WARN")
            warning_codes = {row["code"] for row in finalized["warnings"]}
            self.assertIn("reported_unsettled_after_labels_available", warning_codes)
            self.assertIn("reported_mark_to_market_diverges_from_settlement", warning_codes)

    def test_finalize_taker_run_flags_seattle_resolved_mark_outlier(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = write_taker_run(
                root,
                "taker-20260619-3d3450f0",
                [
                    order_row(
                        "seattle",
                        "highest-temperature-in-seattle-on-june-19-2026",
                        "82-83 F",
                        82,
                        83,
                        1250.0,
                        10.0,
                    )
                ],
                reported_net=1238.75,
                reported_mtm=1238.75,
                reported_unsettled=1,
            )
            labels = root / "market_day_labels.csv"
            write_labels(labels, [
                {
                    "event_slug": "highest-temperature-in-seattle-on-june-19-2026",
                    "market_id": "seattle",
                    "target_date": "2026-06-19",
                    "settlement_bucket": 80,
                    "winning_band": "80-81 F",
                    "quality_grade": "complete",
                }
            ])

            finalized = finalize_taker_run(run, labels_csv=labels, now="2026-06-20T12:00:00+00:00")

            self.assertEqual(finalized["summary"]["settled_order_count"], 1)
            self.assertEqual(finalized["summary"]["unsettled_order_count"], 0)
            self.assertAlmostEqual(finalized["summary"]["net_pnl_usdc"], -10.0)
            warning_codes = {row["code"] for row in finalized["warnings"]}
            self.assertIn("resolved_mark_to_market_outlier", warning_codes)
            self.assertIn("resolved_mark_to_market_sign_flip", warning_codes)

    def test_strategy_bakeoff_blocks_seattle_stale_mtm_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = write_taker_run(
                root,
                "taker-20260619-3d3450f0",
                [
                    order_row(
                        "seattle",
                        "highest-temperature-in-seattle-on-june-19-2026",
                        "82-83 F",
                        82,
                        83,
                        1250.0,
                        10.0,
                        fair_probability=0.95,
                        mark_pnl=1238.75,
                    )
                ],
                reported_net=1238.75,
                reported_mtm=1238.75,
                reported_unsettled=1,
            )
            labels = root / "market_day_labels.csv"
            write_labels(labels, [
                {
                    "event_slug": "highest-temperature-in-seattle-on-june-19-2026",
                    "market_id": "seattle",
                    "target_date": "2026-06-19",
                    "settlement_bucket": 80,
                    "winning_band": "80-81 F",
                    "quality_grade": "complete",
                }
            ])

            bakeoff = run_taker_strategy_bakeoff(
                run,
                labels_csv=labels,
                strategies="raw_edge_control",
                budget_usdc=100,
                out_json=root / "seattle-bakeoff.json",
                out_report=root / "seattle-bakeoff.md",
                now="2026-06-20T12:00:00+00:00",
            )
            gate = bakeoff["promotion_gates"][0]

        self.assertEqual(bakeoff["schema_version"], STRATEGY_BAKEOFF_SCHEMA_VERSION)
        self.assertEqual(gate["status"], "BLOCK")
        self.assertIn("non_negative_settled_roi", gate["failed_gates"])
        self.assertIn("no_resolved_stale_mark_sign_flips", gate["failed_gates"])
        self.assertEqual(gate["stale_mark_sign_flip_count"], 1)
        self.assertAlmostEqual(gate["net_pnl_usdc"], -10.0)

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

    def test_weak_slot_gate_blocks_raw_edge_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                captured_at="2026-06-14T13:30:00+00:00",
                book_captured_at="2026-06-14T13:30:10+00:00",
                bands=[(80, "0.70", "0.60")],
            )
            gate_path = root / "ten_minute_gate.json"
            gate_path.write_text(json.dumps({
                "ten_minute_performance_gate": {
                    "status": "BLOCK",
                    "first_blocker": {"gate": "weak_slot_brier_regression"},
                    "weak_slots": {"slot_minutes": [570], "slot_labels": ["09:30"]},
                }
            }), encoding="utf-8")

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=12,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now="2026-06-14T13:31:00+00:00",
                config={
                    "min_edge": 0.05,
                    "max_order_usdc": 10,
                    "max_position_per_token_usdc": 10,
                    "weak_slot_guard_report_path": str(gate_path),
                    "early_hour_block_guarded_current_high": False,
                },
            )
            orders = read_csv(Path(payload["orders_path"]))

        self.assertEqual(payload["summary"]["latest_tick_filled_orders"], 0)
        self.assertEqual(payload["summary"]["weak_slot_blocked_rows"], 1)
        self.assertTrue(any(row["reason_code"] == "NO_TRADE_WEAK_SLOT_KILL_SWITCH" for row in orders))

    def test_market_centered_warm_tail_guard_blocks_raw_warm_band(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                bands=[(80, "0.30", "0.28"), (84, "0.70", "0.60")],
            )

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=12,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now=NOW,
                config={
                    "min_edge": 0.05,
                    "max_order_usdc": 10,
                    "max_position_per_token_usdc": 10,
                },
            )
            orders = read_csv(Path(payload["orders_path"]))

        warm_rows = [row for row in orders if row["range_label"] == "84-85 F"]
        self.assertEqual(payload["summary"]["latest_tick_filled_orders"], 0)
        self.assertEqual(payload["summary"]["market_centered_warm_tail_blocked_rows"], 1)
        self.assertEqual(warm_rows[0]["market_modal_band_key"], "eq:80-81")
        self.assertEqual(warm_rows[0]["reason_code"], "NO_TRADE_MARKET_CENTERED_WARM_TAIL")

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
                    "market_centered_warm_tail_guard_enabled": False,
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
