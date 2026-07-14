import csv
import gc
import json
import os
import tempfile
import unittest
import weakref
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from weather.market import exchange_economics
from weather.market.taker_bot import (
    DEFAULT_CONFIG,
    DEFAULT_BAKEOFF_STRATEGIES,
    FINALIZATION_SCHEMA_VERSION,
    ORDER_COLUMNS,
    STRATEGY_BAKEOFF_SCHEMA_VERSION,
    CHAMPION_CHALLENGER_LEDGER_SCHEMA_VERSION,
    apply_taker_budget,
    bad_tail_no_go_state,
    bakeoff_needs_refresh,
    build_champion_challenger_ledger,
    build_pnl_payload,
    build_run_once,
    build_taker_edge_permission_map,
    rows_from_order_tapes,
    candidate_skip_reason,
    clustered_taker_promotion_statistics,
    current_high_trust_config_warnings,
    enrich_taker_risk_fields,
    finalization_watchdog,
    finalize_taker_run,
    no_side_campaign_summary,
    next_run_policy_gate,
    recover_run_artifacts_from_orders,
    run_loop,
    run_taker_strategy_bakeoff,
    warm_tail_guard_state,
    weak_slot_gate_state,
    verify_taker_profitability_artifacts,
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
    cadence_fields=None,
    ask_size_at_best="40",
    ask_depth_1pct="40",
    include_no_book=False,
    no_best_bid="0.38",
    no_best_ask="0.40",
    no_bid_size_at_best="25",
    no_ask_size_at_best="25",
    no_ask_depth_1pct="25",
    snapshot_extra_fields_by_value=None,
):
    snapshots_root = root / "snapshots"
    folder = snapshots_root / EVENT
    folder.mkdir(parents=True)
    snapshot_rows = []
    clob_rows = []
    book_rows = []
    token_rows = []
    bands = bands or [(80, "0.70", "0.60"), (82, "0.52", "0.51")]
    snapshot_extra_fields_by_value = snapshot_extra_fields_by_value or {}
    for value, fair, ask in bands:
        token = "" if blank_tokens or (missing_token and value == 80) else f"token-{value}"
        no_token = f"no-token-{value}" if include_no_book and token else ""
        condition = "" if blank_tokens else f"condition-{value}"
        label = f"{value}-{value + 1} F"
        snapshot = {
            "snapshot_id": "s1",
            "captured_at_utc": captured_at,
            "event_slug": EVENT,
            "model_version": "candidate",
            "range_label": label,
            "condition_id": condition,
            "clob_yes_token_id": token,
            "clob_no_token_id": no_token,
            "bin_kind": "eq",
            "bin_value_c": str(value),
            "model_probability": fair,
            "market_yes": "0.50",
            "market_status": "active",
            "snapshot_cadence": "scheduled",
            "current_high_trusted": "True",
            "taker_edge_permission": "edge_allowed",
            "taker_edge_permission_reason": "fixture_settlement_skill",
            "taker_edge_permission_sample_size": "10",
            "taker_edge_permission_independent_days": "5",
            "taker_edge_permission_market_count": "1",
            "taker_edge_permission_after_fee_skill": "0.10",
            "taker_edge_permission_hit_rate": fair,
            "taker_skill_weight": "1.0",
            "calibrated_model_probability": fair,
            "calibrated_fair_probability": fair,
            "calibrated_fair": fair,
        }
        snapshot.update(cadence_fields or {})
        snapshot.update(snapshot_extra_fields_by_value.get(value) or {})
        snapshot_rows.append(snapshot)
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
            "clob_no_token_id": no_token,
            "clob_book_captured_at_utc": book_captured_at,
            "clob_book_age_seconds": "10",
            "clob_midpoint": "0.55",
            "clob_best_bid": "0.50",
            "clob_best_ask": ask,
            "clob_depth_1pct_total": ask_depth_1pct,
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
            "ask_size_at_best": ask_size_at_best,
            "bid_size_at_best": "40",
            "ask_depth_1pct": ask_depth_1pct,
            "bid_depth_1pct": "40",
            "min_order_size": "1",
            "tick_size": "0.001",
        })
        if no_token:
            book_rows.append({
                "captured_at_utc": book_captured_at,
                "event_slug": EVENT,
                "market_id": "atlanta",
                "range_label": label,
                "bin_kind": "eq",
                "bin_value": str(value),
                "bin_value_hi": str(value + 1),
                "condition_id": condition,
                "clob_token_id": no_token,
                "outcome": "no",
                "best_bid": no_best_bid,
                "best_ask": no_best_ask,
                "midpoint": "0.39",
                "ask_size_at_best": no_ask_size_at_best,
                "bid_size_at_best": no_bid_size_at_best,
                "ask_depth_1pct": no_ask_depth_1pct,
                "bid_depth_1pct": no_bid_size_at_best,
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
        if no_token:
            token_rows.append({
                "event_slug": EVENT,
                "market_id": "atlanta",
                "condition_id": condition,
                "range_label": label,
                "bin_kind": "eq",
                "bin_value": str(value),
                "bin_value_hi": str(value + 1),
                "outcome": "no",
                "clob_token_id": no_token,
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
        "taker_edge_permission": "edge_allowed",
        "taker_edge_permission_reason": "fixture_settlement_skill",
        "taker_skill_weight": "1.0",
        "calibrated_model_probability": str(fair_probability),
        "calibrated_fair_probability": str(fair_probability),
        "calibrated_fair": str(fair_probability),
        "calibrated_edge": str(float(fair_probability) - fill_price),
        "taker_edge_permission_hit_rate": str(fair_probability),
        "ask_size_at_best": str(fill_size),
        "book_age_seconds": "10",
        "model_age_seconds": "10",
        "source_fresh": "True",
        "source_freshness_state": "all_fresh",
        "snapshot_cadence": "scheduled",
        "current_high_trust_state_present": "True",
        "current_high_trusted": "True",
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
    for row in rows:
        for field in row:
            if field not in fieldnames:
                fieldnames.append(field)
    write_csv(path, fieldnames, rows)


class TestTakerBot(unittest.TestCase):
    def test_run_loop_releases_completed_tick_payloads(self):
        class Payload:
            pass

        payload_refs = []
        payload_liveness_during_sleep = []

        def build_payload(*_args, **_kwargs):
            payload = Payload()
            payload_refs.append(weakref.ref(payload))
            return payload

        def observe_sleep(_seconds):
            gc.collect()
            payload_liveness_during_sleep.append(
                tuple(payload_ref() is not None for payload_ref in payload_refs)
            )

        with (
            patch(
                "weather.market.taker_bot_cli.build_run_once",
                side_effect=build_payload,
            ) as build_mock,
            patch(
                "weather.market.taker_bot_cli.keep_system_awake",
                return_value=nullcontext(),
            ),
            patch(
                "weather.market.taker_bot_cli.time.sleep",
                side_effect=observe_sleep,
            ),
        ):
            result = run_loop(
                TARGET_DATE,
                budget_usdc=100,
                markets="atlanta",
                interval_seconds=0,
                until_utc="2099-01-01T00:00:00+00:00",
                max_ticks=3,
            )

        self.assertEqual(build_mock.call_count, 3)
        self.assertEqual(
            payload_liveness_during_sleep,
            [(True,), (False, True)],
        )
        self.assertIsNone(payload_refs[0]())
        self.assertIsNone(payload_refs[1]())
        self.assertIs(payload_refs[2](), result)

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
                config={
                    "min_edge": 0.05,
                    "max_order_usdc": 10,
                    "max_position_per_token_usdc": 10,
                    "market_centered_warm_tail_guard_enabled": False,
                },
            )

            self.assertEqual(payload["summary"]["latest_tick_filled_orders"], 1)
            self.assertEqual(payload["summary"]["cumulative_filled_orders"], 1)
            self.assertAlmostEqual(payload["summary"]["budget_spent_usdc"], 10.2)
            self.assertAlmostEqual(payload["summary"]["cumulative_net_pnl_usdc"], 6.466667)
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
            self.assertAlmostEqual(float(filled[0]["fee_usdc"]), 0.2)
            self.assertEqual(filled[0]["pnl_fee_basis"], "after_fee")
            self.assertAlmostEqual(float(filled[0]["settlement_outcome"]), 1.0)
            self.assertTrue(Path(payload["daily_pnl_path"]).exists())
            self.assertTrue(Path(payload["run_report_path"]).exists())
            self.assertIn("Tape integrity", Path(payload["run_report_path"]).read_text(encoding="utf-8"))

    def test_zero_fill_run_writes_settlement_scoreable_counterfactual_tape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                bands=[(80, "0.69", "0.60")],
            )

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=12,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now=NOW,
                strategies="strict_edge_probe",
                config={
                    "min_edge": 0.01,
                    "max_order_usdc": 10,
                    "max_position_per_token_usdc": 10,
                    "market_centered_warm_tail_guard_enabled": False,
                },
            )
            orders_path = Path(payload["orders_path"])
            counterfactual_path = Path(payload["counterfactual_orders_path"])
            raw_before = orders_path.read_text(encoding="utf-8")
            raw_rows = read_csv(orders_path)
            counterfactual_rows = read_csv(counterfactual_path)

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
            finalized = finalize_taker_run(
                Path(payload["run_folder"]),
                labels_csv=labels,
                now="2026-06-15T12:00:00+00:00",
            )
            raw_after = orders_path.read_text(encoding="utf-8")
            counterfactual = finalized["counterfactual"]
            settled_counterfactual_exists = Path(counterfactual["settled_counterfactual_orders_path"]).exists()
            settled_counterfactual_report_exists = Path(counterfactual["settled_counterfactual_report_path"]).exists()

        self.assertEqual(sum(1 for row in raw_rows if row["order_status"] == "FILLED"), 0)
        self.assertGreater(len(counterfactual_rows), len(raw_rows))
        self.assertTrue(any(row["strategy_id"] == "raw_edge_control" for row in counterfactual_rows))
        self.assertTrue(any(row["order_status"] == "FILLED" for row in counterfactual_rows))
        self.assertTrue(any(row["real_strategy_id"] == "strict_edge_probe" for row in counterfactual_rows))
        self.assertEqual(raw_after, raw_before)
        self.assertEqual(counterfactual["status"], "SCORED")
        self.assertTrue(counterfactual["summary"]["zero_real_fill_learning"])
        self.assertGreater(counterfactual["summary"]["would_buy_count"], 0)
        self.assertGreater(counterfactual["summary"]["settled_would_buy_count"], 0)
        self.assertTrue(settled_counterfactual_exists)
        self.assertTrue(settled_counterfactual_report_exists)

    def test_counterfactual_tape_scores_model_variant_strategy_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                bands=[(80, "0.45", "0.60")],
                snapshot_extra_fields_by_value={
                    80: {
                        "dynamic_source_probability": "0.80",
                        "exact_winner_probability": "0.40",
                    }
                },
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
                    "market_centered_warm_tail_guard_enabled": False,
                    "taker_model_variant_basket": "served_current,dynamic_source_state,exact_winner_catchup",
                    "counterfactual_strategies": "raw_edge_control",
                },
            )
            counterfactual_rows = read_csv(Path(payload["counterfactual_orders_path"]))
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
            finalized = finalize_taker_run(
                Path(payload["run_folder"]),
                labels_csv=labels,
                now="2026-06-15T12:00:00+00:00",
            )
            model_bakeoff = finalized["counterfactual"]["model_variant_bakeoff"]
            pairs = {
                (row["model_variant_id"], row["strategy_id"]): row
                for row in model_bakeoff["pairs"]
            }

        self.assertEqual(
            payload["summary"]["counterfactual_model_variant_manifest"]["materialized_variant_ids"],
            ["dynamic_source_state", "exact_winner_catchup", "served_current"],
        )
        self.assertEqual(
            {row["model_variant_id"] for row in counterfactual_rows},
            {"served_current", "dynamic_source_state", "exact_winner_catchup"},
        )
        self.assertEqual(model_bakeoff["multiple_testing_method"], "bonferroni_pre_registered_basket")
        self.assertIn(("dynamic_source_state", "raw_edge_control"), pairs)
        self.assertGreater(float(pairs[("dynamic_source_state", "raw_edge_control")]["net_pnl_usdc"]), 0.0)
        self.assertGreater(
            float(pairs[("dynamic_source_state", "raw_edge_control")]["delta_vs_served_current_net_pnl_usdc"]),
            0.0,
        )
        self.assertIn(
            "min_settled_would_buy",
            pairs[("dynamic_source_state", "raw_edge_control")]["variant_selection_failed_gates"],
        )

    def test_clustered_promotion_blocks_many_same_day_rows_without_market_day_diversity(self):
        rows = [
            {
                "target_date": "2026-06-14",
                "market_id": "atlanta",
                "model_variant_id": "dynamic_source_state",
                "strategy_id": "raw_edge_control",
                "order_status": "FILLED",
                "pnl_source": "settlement_finalized",
                "total_spent_usdc": "1",
                "net_pnl_usdc": "0.25",
                "settlement_outcome": "1",
                "pnl_fee_basis": "after_fee",
                "after_fee_pnl_scored": "True",
                "after_slippage_pnl_scored": "True",
                "executable_depth_model_version": "top_of_book_plus_1pct_depth_v1",
            }
            for _ in range(40)
        ]

        gate = clustered_taker_promotion_statistics(
            rows,
            min_independent_target_days=3,
            min_independent_markets=2,
        )
        pair = gate["pairs"][0]

        self.assertEqual(gate["status"], "BLOCK")
        self.assertEqual(pair["cluster_count"], 1)
        self.assertEqual(pair["would_buy_count"], 40)
        self.assertIn("min_independent_target_days", pair["failed_gates"])
        self.assertIn("min_independent_markets", pair["failed_gates"])

    def test_clustered_promotion_can_pass_across_independent_market_days(self):
        rows = []
        for target_date, market_id in [
            ("2026-06-14", "atlanta"),
            ("2026-06-15", "atlanta"),
            ("2026-06-16", "dallas"),
        ]:
            rows.append({
                "target_date": target_date,
                "market_id": market_id,
                "model_variant_id": "dynamic_source_state",
                "strategy_id": "raw_edge_control",
                "order_status": "FILLED",
                "pnl_source": "settlement_finalized",
                "total_spent_usdc": "1",
                "net_pnl_usdc": "0.25",
                "settlement_outcome": "1",
                "pnl_fee_basis": "after_fee",
                "after_fee_pnl_scored": "True",
                "after_slippage_pnl_scored": "True",
                "executable_depth_model_version": "top_of_book_plus_1pct_depth_v1",
            })

        gate = clustered_taker_promotion_statistics(
            rows,
            min_independent_target_days=3,
            min_independent_markets=2,
        )
        pair = gate["pairs"][0]

        self.assertEqual(gate["status"], "PASS")
        self.assertEqual(pair["cluster_count"], 3)
        self.assertEqual(pair["independent_target_day_count"], 3)
        self.assertEqual(pair["independent_market_count"], 2)
        self.assertEqual(pair["failed_gates"], [])

    def test_two_sided_taker_captures_real_no_book_depth_in_order_tape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                bands=[(80, "0.30", "0.60")],
                include_no_book=True,
                no_best_bid="0.38",
                no_best_ask="0.40",
                no_ask_size_at_best="25",
                no_ask_depth_1pct="25",
            )

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=12,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now=NOW,
                strategies="fade_overpriced",
                config={
                    "min_edge": 0.05,
                    "max_order_usdc": 10,
                    "max_position_per_token_usdc": 10,
                    "market_centered_warm_tail_guard_enabled": False,
                },
            )
            orders = read_csv(Path(payload["orders_path"]))
            filled_no = [
                row
                for row in orders
                if row["order_status"] == "FILLED" and row["side"] == "NO_BUY"
            ]

        self.assertEqual(len(filled_no), 1)
        row = filled_no[0]
        self.assertEqual(row["clob_token_id"], "no-token-80")
        self.assertEqual(row["clob_yes_token_id"], "token-80")
        self.assertEqual(row["clob_no_token_id"], "no-token-80")
        self.assertEqual(row["no_book_source"], "no_token_book")
        self.assertEqual(row["no_book_fresh"], "True")
        self.assertEqual(row["real_no_book_depth_eligible"], "True")
        self.assertAlmostEqual(float(row["best_ask"]), 0.40)
        self.assertAlmostEqual(float(row["no_ask_size_at_best"]), 25.0)
        self.assertAlmostEqual(float(row["no_ask_depth_1pct"]), 25.0)

    def test_default_counterfactual_campaign_collects_real_no_side_fade_evidence(self):
        self.assertIn("fade_overpriced", DEFAULT_BAKEOFF_STRATEGIES.split(","))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                bands=[(80, "0.30", "0.60")],
                include_no_book=True,
                no_best_bid="0.38",
                no_best_ask="0.40",
                no_ask_size_at_best="25",
                no_ask_depth_1pct="25",
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
                    "market_centered_warm_tail_guard_enabled": False,
                },
            )
            counterfactual_rows = read_csv(Path(payload["counterfactual_orders_path"]))
            no_rows = [
                row for row in counterfactual_rows
                if row["strategy_id"] == "fade_overpriced" and row["side"] == "NO_BUY"
            ]

            labels = root / "market_day_labels.csv"
            write_labels(labels, [
                {
                    "event_slug": EVENT,
                    "market_id": "atlanta",
                    "target_date": TARGET_DATE,
                    "settlement_bucket": 79,
                    "winning_band": "79-80 F",
                    "quality_grade": "complete",
                }
            ])
            finalized = finalize_taker_run(
                Path(payload["run_folder"]),
                labels_csv=labels,
                now="2026-06-15T12:00:00+00:00",
            )
            campaign = finalized["counterfactual"]["no_side_campaign"]
            report_text = Path(finalized["counterfactual"]["settled_counterfactual_report_path"]).read_text(
                encoding="utf-8",
            )

        self.assertGreater(len(no_rows), 0)
        self.assertTrue(any(row["order_status"] == "FILLED" for row in no_rows))
        self.assertTrue(all(row["no_book_source"] == "no_token_book" for row in no_rows))
        self.assertTrue(any(row["real_no_book_depth_eligible"] == "True" for row in no_rows))
        self.assertEqual(campaign["status"], "COLLECTING_SETTLED_NO_SIDE")
        self.assertGreater(campaign["real_no_book_row_count"], 0)
        self.assertGreater(campaign["countable_no_side_would_buy_count"], 0)
        self.assertGreater(campaign["settled_countable_no_side_would_buy_count"], 0)
        self.assertEqual(campaign["synthetic_only_countable"], False)
        self.assertGreater(campaign["countable_no_side_net_pnl_usdc"], 0.0)
        self.assertTrue(campaign["by_market"])
        self.assertTrue(campaign["by_hour"])
        self.assertIn("NO-Side Campaign", report_text)
        self.assertIn("NO-Side by Strategy", report_text)
        self.assertEqual(
            finalized["summary"]["counterfactual_no_side_campaign_status"],
            "COLLECTING_SETTLED_NO_SIDE",
        )

    def test_no_side_campaign_summary_keeps_synthetic_only_evidence_non_countable(self):
        rows = [
            {
                "run_id": "r1",
                "target_date": TARGET_DATE,
                "generated_at_utc": NOW,
                "captured_at_utc": NOW,
                "strategy_id": "fade_overpriced",
                "strategy_family": "two_sided",
                "side": "NO_BUY",
                "order_status": "FILLED",
                "reason_code": "BUY_EDGE",
                "market_id": "atlanta",
                "event_slug": EVENT,
                "range_label": "80-81 F",
                "bin_kind": "eq",
                "bin_value": "80",
                "bin_value_hi": "81",
                "total_spent_usdc": "4.2",
                "net_pnl_usdc": "5.8",
                "settlement_outcome": "1",
                "pnl_source": "settlement_finalized",
                "no_book_source": "synthetic_from_yes_bid",
                "no_book_fresh": "True",
                "real_no_book_depth_eligible": "False",
            }
        ]

        summary = no_side_campaign_summary(rows)
        pnl = build_pnl_payload(
            rows,
            12,
            "r1",
            TARGET_DATE,
            now="2026-06-15T12:00:00+00:00",
        )
        strategy = pnl["by_strategy"][0]

        self.assertEqual(summary["status"], "BLOCK_NO_REAL_NO_BOOK_ROWS")
        self.assertEqual(summary["no_side_would_buy_count"], 1)
        self.assertEqual(summary["countable_no_side_would_buy_count"], 0)
        self.assertEqual(summary["synthetic_no_book_would_buy_count"], 1)
        self.assertEqual(summary["synthetic_only_countable"], False)
        self.assertEqual(strategy["settlement_promotion_gate_status"], "BLOCK")
        self.assertIn("real_no_book_depth_for_two_sided", strategy["settlement_promotion_failed_gates"])

    def test_depth_aware_fill_records_slippage_when_size_exceeds_top_of_book(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                ask_size_at_best="1",
                ask_depth_1pct="40",
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
                    "market_centered_warm_tail_guard_enabled": False,
                },
            )
            filled = [row for row in read_csv(Path(payload["orders_path"])) if row["order_status"] == "FILLED"]

        self.assertEqual(len(filled), 1)
        self.assertGreater(float(filled[0]["fill_size"]), 1.0)
        self.assertGreater(float(filled[0]["fill_price"]), float(filled[0]["best_ask"]))
        self.assertGreater(float(filled[0]["slippage_usdc"]), 0.0)
        self.assertEqual(filled[0]["executable_depth_mode"], "top_of_book_plus_1pct_depth")

    def test_pre_fee_positive_edge_can_fail_after_executable_friction_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(root, settled=True, bands=[(80, "0.61", "0.60")])

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=12,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now=NOW,
                config={"min_edge": 0.005, "max_order_usdc": 10, "max_position_per_token_usdc": 10},
            )
            orders = read_csv(Path(payload["orders_path"]))
            filled = [row for row in orders if row["order_status"] == "FILLED"]
            skipped = [row for row in orders if row["reason_code"] == "NO_TRADE_AFTER_COST_EV_TOO_SMALL"]
            strategy = payload["pnl"]["by_strategy"][0]

        self.assertEqual(len(filled), 0)
        self.assertEqual(len(skipped), 1)
        self.assertGreater(float(skipped[0]["edge"]), 0.0)
        self.assertLess(float(skipped[0]["expected_profit_after_friction_per_share"]), 0.0)
        self.assertEqual(strategy["settlement_scored_expected_pnl_usdc"], 0.0)
        self.assertEqual(payload["summary"]["latest_tick_filled_orders"], 0)

    def test_unpermissioned_slice_shrinks_calibrated_fair_to_market_and_no_trades(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                bands=[(80, "0.80", "0.60")],
                snapshot_extra_fields_by_value={
                    80: {
                        "taker_edge_permission": "deny",
                        "taker_edge_permission_reason": "fixture_unproven_slice",
                        "taker_skill_weight": "0.0",
                        "calibrated_model_probability": "0.20",
                    }
                },
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
                    "market_centered_warm_tail_guard_enabled": False,
                },
            )
            orders = read_csv(Path(payload["orders_path"]))

        self.assertEqual(payload["summary"]["latest_tick_filled_orders"], 0)
        row = orders[0]
        self.assertEqual(row["reason_code"], "NO_TRADE_EDGE_NOT_PERMISSIONED")
        self.assertEqual(row["taker_edge_permission"], "deny")
        self.assertEqual(float(row["taker_skill_weight"]), 0.0)
        self.assertAlmostEqual(float(row["calibrated_fair"]), float(row["market_implied_probability"]))
        self.assertLessEqual(float(row["calibrated_edge"]), 0.0)

    def test_market_no_trade_precondition_blocks_permissioned_slice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                bands=[(80, "0.80", "0.60")],
                snapshot_extra_fields_by_value={
                    80: {
                        "market_benchmark_recommendation": "no_trade_market_smarter",
                    }
                },
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
                    "market_centered_warm_tail_guard_enabled": False,
                },
            )
            orders = read_csv(Path(payload["orders_path"]))

        self.assertEqual(payload["summary"]["latest_tick_filled_orders"], 0)
        self.assertEqual(orders[0]["reason_code"], "NO_TRADE_MARKET_BENCHMARK_NO_TRADE")
        self.assertEqual(orders[0]["market_benchmark_precondition"], "no_trade")

    def test_budget_allocation_ranks_by_calibrated_after_cost_ev_not_raw_edge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                bands=[(80, "0.95", "0.80"), (82, "0.72", "0.60")],
                snapshot_extra_fields_by_value={
                    80: {
                        "taker_skill_weight": "0.10",
                        "calibrated_model_probability": "0.95",
                        "calibrated_fair_probability": "",
                        "calibrated_fair": "",
                    },
                    82: {
                        "taker_skill_weight": "1.0",
                        "calibrated_model_probability": "0.72",
                        "calibrated_fair_probability": "0.72",
                        "calibrated_fair": "0.72",
                    },
                },
            )

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=20,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now=NOW,
                config={
                    "min_edge": 0.05,
                    "max_order_usdc": 10,
                    "max_position_per_token_usdc": 10,
                    "max_daily_positions": 1,
                    "market_centered_warm_tail_guard_enabled": False,
                },
            )
            filled = [row for row in read_csv(Path(payload["orders_path"])) if row["order_status"] == "FILLED"]

        self.assertEqual(len(filled), 1)
        self.assertEqual(filled[0]["range_label"], "82-83 F")
        self.assertGreater(float(filled[0]["after_cost_ev_per_share"]), 0.0)

    def test_taker_permission_map_builder_promotes_only_settlement_scored_skill_cells(self):
        skill_rows = []
        for index in range(5):
            skill_rows.append({
                "target_date": f"2026-06-{14 + index:02d}",
                "market_id": "atlanta",
                "captured_at_utc": f"2026-06-{14 + index:02d}T16:00:00+00:00",
                "capture_hour_local": "12",
                "range_label": "80-81 F",
                "bin_kind": "eq",
                "bin_value": "80",
                "bin_value_hi": "81",
                "side": "YES_BUY",
                "source_freshness_state": "all_fresh",
                "snapshot_cadence_quality_state": "clean",
                "current_high_trusted": "True",
                "current_high_band_distance": "0",
                "model_variant_id": "served_current",
                "fair_probability": "0.90",
                "market_mid": "0.55",
                "best_ask": "0.60",
                "settlement_outcome": "1",
            })
        weak_rows = [
            {
                **skill_rows[0],
                "target_date": "2026-07-01",
                "market_id": "seattle",
                "fair_probability": "0.90",
                "market_mid": "0.55",
                "best_ask": "0.60",
                "settlement_outcome": "0",
            }
        ]

        payload = build_taker_edge_permission_map(
            [*skill_rows, *weak_rows],
            now="2026-07-10T00:00:00+00:00",
            min_settled_orders=5,
            min_independent_days=3,
        )
        records = {(row["market_id"], row["permission"]): row for row in payload["records"]}

        self.assertEqual(payload["schema_version"], "taker_edge_permission_map_v0.1")
        self.assertIn(("atlanta", "edge_allowed"), records)
        self.assertIn(("seattle", "observe"), records)
        self.assertGreater(records[("atlanta", "edge_allowed")]["taker_skill_weight"], 0.0)

    def test_taker_permission_tapes_are_loaded_lazily_one_at_a_time(self):
        row = {
            "market_id": "atlanta",
            "settlement_outcome": "1",
        }

        with patch(
            "weather.market.taker_edge_permission.read_csv_rows",
            side_effect=lambda path, **_kwargs: [{**row, "target_date": str(path)}],
        ) as read_rows:
            rows = rows_from_order_tapes(["day-one.csv", "day-two.csv"])
            self.assertEqual(read_rows.call_count, 0)
            self.assertEqual(next(rows)["target_date"], "day-one.csv")
            self.assertEqual(read_rows.call_count, 1)
            self.assertEqual(next(rows)["target_date"], "day-two.csv")
            self.assertEqual(read_rows.call_count, 2)
            with self.assertRaises(StopIteration):
                next(rows)

    def test_market_benchmark_blocks_when_market_top_beats_model_trade_after_fees(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                bands=[
                    (80, "0.50", "0.70"),
                    (82, "0.80", "0.60"),
                    (84, "0.10", "0.05"),
                ],
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
                    "market_centered_warm_tail_guard_enabled": False,
                },
            )
            filled = [row for row in read_csv(Path(payload["orders_path"])) if row["order_status"] == "FILLED"]
            strategy = payload["pnl"]["by_strategy"][0]
            benchmark = payload["pnl"]["market_benchmark_scoreboard"]

        self.assertEqual(filled[0]["range_label"], "82-83 F")
        self.assertEqual(strategy["market_benchmark_status"], "BLOCK_MARKET_SMARTER")
        self.assertIn("market_benchmark_beats_model", strategy["settlement_promotion_failed_gates"])
        self.assertFalse(strategy["quality_candidate_countable"])
        self.assertEqual(benchmark["summary"]["market_smarter_slice_count"], 1)
        self.assertGreater(benchmark["summary"]["missed_gain_usdc"], 0.0)
        self.assertGreater(benchmark["summary"]["avoided_loss_usdc"], 0.0)

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
        self.assertAlmostEqual(by_strategy["raw_edge_control"]["spent_usdc"], 10.2)
        self.assertAlmostEqual(by_strategy["small_order_probe"]["spent_usdc"], 1.02)
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
                config={
                    "max_order_usdc": 10,
                    "max_position_per_token_usdc": 10,
                    "current_high_trust_gate_enabled": False,
                },
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

    def test_snapshot_cadence_gap_blocks_taker_buy_despite_fresh_source_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                bands=[(80, "0.95", "0.60")],
                cadence_fields={
                    "snapshot_cadence": "scheduled",
                    "snapshot_cadence_gap_count": "2",
                    "snapshot_cadence_max_gap_seconds": "1328.4",
                },
            )

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=100,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now=NOW,
                config={"max_order_usdc": 10, "max_position_per_token_usdc": 10},
            )
            orders = read_csv(Path(payload["orders_path"]))

        self.assertEqual(payload["summary"]["latest_tick_filled_orders"], 0)
        row = orders[0]
        self.assertEqual(row["reason_code"], "NO_TRADE_SNAPSHOT_CADENCE_DEGRADED")
        self.assertEqual(row["snapshot_cadence_quality_state"], "gappy")
        self.assertEqual(row["snapshot_cadence_permission"], "deny")
        self.assertIn("cadence_quality:gappy", row["reliability_reason"])
        self.assertLess(float(row["reliability_confidence"]), 1.0)
        self.assertLess(float(row["reliability_adjusted_fair_probability"]), float(row["fair_probability"]))

    def test_missing_snapshot_cadence_state_blocks_taker_buy_by_default(self):
        row = {
            "market_id": "atlanta",
            "event_slug": EVENT,
            "snapshot_id": "s1",
            "captured_at_utc": "2026-06-14T14:00:00+00:00",
            "capture_hour_local": "10",
            "range_label": "84-85 F",
            "bin_kind": "eq",
            "bin_value": "84",
            "bin_value_hi": "85",
            "clob_token_id": "token-84",
            "fair_probability": "0.30",
            "best_ask": "0.10",
            "best_bid": "0.09",
            "edge": "0.20",
            "ask_size_at_best": "50",
            "book_age_seconds": "10",
            "model_age_seconds": "10",
            "source_fresh": "True",
            "source_freshness_state": "all_fresh",
            "current_high_trust_state_present": "True",
            "current_high_trusted": "True",
        }

        enriched = enrich_taker_risk_fields(row, {**DEFAULT_CONFIG, "min_edge": 0.03})
        reason, detail = candidate_skip_reason(enriched, {**DEFAULT_CONFIG, "min_edge": 0.03})

        self.assertEqual(reason, "NO_TRADE_SNAPSHOT_CADENCE_DEGRADED")
        self.assertEqual(enriched["snapshot_cadence_quality_state"], "missing")
        self.assertEqual(enriched["snapshot_cadence_permission"], "deny")
        self.assertFalse(enriched["snapshot_cadence_state_present"])
        self.assertIn("missing snapshot cadence quality state", detail)

    def test_late_untrusted_current_high_blocks_aggressive_taker_for_june_21_markets(self):
        cases = {
            "toronto": (84.0, 86.0),
            "atlanta": (84.02, 86.0),
            "denver": (83.84, 87.0),
            "houston": (86.0, 89.0),
            "san-francisco": (64.94, 70.0),
        }
        config = {**DEFAULT_CONFIG, "min_edge": 0.03}
        for market_id, (raw_high, settlement_high) in cases.items():
            with self.subTest(market_id=market_id):
                row = {
                    "market_id": market_id,
                    "event_slug": f"highest-temperature-in-{market_id}-on-june-21-2026",
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-21T20:00:00+00:00",
                    "capture_hour_local": "16",
                    "range_label": f"{int(settlement_high)}-{int(settlement_high) + 1} F",
                    "bin_kind": "eq",
                    "bin_value": str(int(settlement_high)),
                    "bin_value_hi": str(int(settlement_high) + 1),
                    "clob_token_id": f"token-{market_id}",
                    "fair_probability": "0.30",
                    "best_ask": "0.10",
                    "best_bid": "0.09",
                    "market_mid": "0.095",
                    "edge": "0.20",
                    "ask_size_at_best": "50",
                    "book_age_seconds": "10",
                    "model_age_seconds": "10",
                    "source_fresh": "True",
                    "source_freshness_state": "all_fresh",
                    "snapshot_cadence": "scheduled",
                    "raw_current_high": str(raw_high),
                    "raw_current_high_bucket": str(round(raw_high)),
                    "settlement_current_high": str(settlement_high),
                    "current_high_trusted": "False",
                    "current_high_guard_reason": "settlement_adjusted_high_diverged_from_raw_current_high",
                    "current_max_state": "current_max_history_gap",
                }
                enriched = enrich_taker_risk_fields(row, config)
                reason, detail = candidate_skip_reason(enriched, config)

                self.assertEqual(reason, "NO_TRADE_CURRENT_HIGH_TRUST_GATE")
                self.assertEqual(enriched["current_high_trust_gate_status"], "blocked")
                self.assertEqual(enriched["current_high_trust_gate_action"], "deny_aggressive")
                self.assertTrue(enriched["current_high_trust_gate_aggressive"])
                self.assertIn("untrusted_current_high", detail)

    def test_missing_current_high_trust_state_blocks_aggressive_taker(self):
        row = {
            "market_id": "atlanta",
            "event_slug": EVENT,
            "snapshot_id": "s1",
            "captured_at_utc": "2026-06-14T14:00:00+00:00",
            "capture_hour_local": "10",
            "range_label": "84-85 F",
            "bin_kind": "eq",
            "bin_value": "84",
            "bin_value_hi": "85",
            "clob_token_id": "token-84",
            "fair_probability": "0.30",
            "best_ask": "0.10",
            "best_bid": "0.09",
            "edge": "0.20",
            "ask_size_at_best": "50",
            "book_age_seconds": "10",
            "model_age_seconds": "10",
            "source_fresh": "True",
            "source_freshness_state": "all_fresh",
            "snapshot_cadence": "scheduled",
        }

        enriched = enrich_taker_risk_fields(row, {**DEFAULT_CONFIG, "min_edge": 0.03})
        reason, detail = candidate_skip_reason(enriched, {**DEFAULT_CONFIG, "min_edge": 0.03})

        self.assertEqual(reason, "NO_TRADE_CURRENT_HIGH_TRUST_GATE")
        self.assertEqual(enriched["current_high_trust_gate_status"], "blocked")
        self.assertEqual(enriched["current_high_trust_gate_action"], "deny_missing_trust_state")
        self.assertIn("missing_current_high_trust_state", detail)

    def test_current_high_trust_gate_start_hour_drift_still_blocks_aggressive_taker(self):
        row = {
            "market_id": "atlanta",
            "event_slug": EVENT,
            "snapshot_id": "s1",
            "captured_at_utc": "2026-06-14T13:30:00+00:00",
            "capture_hour_local": "9",
            "range_label": "84-85 F",
            "bin_kind": "eq",
            "bin_value": "84",
            "bin_value_hi": "85",
            "clob_token_id": "token-84",
            "fair_probability": "0.30",
            "best_ask": "0.10",
            "best_bid": "0.09",
            "edge": "0.20",
            "ask_size_at_best": "50",
            "book_age_seconds": "10",
            "model_age_seconds": "10",
            "source_fresh": "True",
            "source_freshness_state": "all_fresh",
            "snapshot_cadence": "scheduled",
            "current_high_trust_state_present": "True",
            "current_high_trusted": "False",
            "current_max_state": "current_max_history_gap",
        }
        config = {
            **DEFAULT_CONFIG,
            "min_edge": 0.03,
            "current_high_trust_gate_start_hour_local": 15,
        }

        enriched = enrich_taker_risk_fields(row, config)
        reason, detail = candidate_skip_reason(enriched, config)
        warnings = current_high_trust_config_warnings(config)

        self.assertEqual(reason, "NO_TRADE_CURRENT_HIGH_TRUST_GATE")
        self.assertEqual(enriched["current_high_trust_gate_status"], "blocked")
        self.assertEqual(enriched["current_high_trust_gate_action"], "deny_aggressive")
        self.assertTrue(enriched["current_high_trust_gate_aggressive"])
        self.assertIn("hour:9", detail)
        self.assertEqual(warnings[0]["code"], "CURRENT_HIGH_TRUST_GATE_DELAYED_START")
        self.assertEqual(warnings[0]["effective_aggressive_start_hour_local"], 0.0)

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
                config={
                    "max_order_usdc": 10,
                    "max_position_per_token_usdc": 10,
                },
                strategies="low_price_tail_capped",
                experiment_id="tail-sizing-fixture",
            )
            filled = [row for row in read_csv(Path(payload["orders_path"])) if row["order_status"] == "FILLED"]
            strategy = payload["pnl"]["by_strategy"][0]

        self.assertEqual(len(filled), 1)
        row = filled[0]
        self.assertEqual(row["sizing_rule"], "tail_lottery")
        self.assertEqual(row["low_price_tail"], "True")
        self.assertEqual(row["bad_tail_no_go_status"], "allowed")
        self.assertEqual(row["tail_risk_bucket"], "low_price_tail")
        self.assertLessEqual(float(row["requested_notional_usdc"]), 0.5)
        self.assertLessEqual(float(row["fill_notional_usdc"]), 0.5)
        self.assertEqual(strategy["low_price_tail_fill_count"], 1)
        self.assertLessEqual(strategy["low_price_tail_spent_usdc"], 0.5)
        self.assertEqual(payload["summary"]["active_strategy_id"], "low_price_tail_capped")
        self.assertEqual(payload["summary"]["active_strategy_lifecycle"], "candidate_canary")
        self.assertEqual(payload["summary"]["active_strategy_canary"]["strategy_id"], "low_price_tail_capped")

    def test_bad_tail_no_go_blocks_unpermissioned_low_price_tail_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                bands=[(80, "0.40", "0.01")],
                snapshot_extra_fields_by_value={
                    80: {
                        "taker_edge_permission": "deny",
                        "taker_edge_permission_reason": "fixture_unproven_tail_slice",
                        "taker_skill_weight": "0.0",
                    }
                },
            )

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
                experiment_id="tail-no-go-fixture",
            )
            orders = read_csv(Path(payload["orders_path"]))

        self.assertEqual(payload["summary"]["latest_tick_filled_orders"], 0)
        self.assertTrue(any(row["strategy_id"] == "low_price_tail_capped" for row in orders))
        row = orders[0]
        self.assertEqual(row["low_price_tail"], "True")
        self.assertEqual(row["reason_code"], "NO_TRADE_BAD_TAIL_NO_GO")
        self.assertEqual(row["bad_tail_no_go_status"], "blocked")
        self.assertEqual(row["bad_tail_no_go_action"], "no_trade")
        self.assertEqual(row["bad_tail_no_go_slice_id"], "low_price_tail_price_le_0.05")
        self.assertIn("edge_permission:deny", row["bad_tail_no_go_reason"])

    def test_bad_tail_no_go_explicit_star_kill_switch_blocks_permissioned_tail(self):
        state = bad_tail_no_go_state(
            {
                "strategy_family": "tail_risk_sizing",
                "taker_edge_permission": "edge_allowed",
                "low_price_tail": True,
                "best_ask": "0.01",
            },
            {**DEFAULT_CONFIG, "bad_tail_no_go_block_strategy_families": "*"},
        )

        self.assertEqual(state["bad_tail_no_go_status"], "blocked")
        self.assertIn("operator_kill_switch", state["bad_tail_no_go_reason"])

    def test_positive_mtm_zero_settled_tail_heavy_run_is_not_countable(self):
        rows = []
        for index in range(50):
            tail = index < 31
            value = 70 + (index % 10)
            row = order_row(
                "atlanta",
                EVENT,
                f"{value}-{value + 1} F",
                value,
                value + 1,
                fill_size=10,
                fill_notional=0.2 if tail else 3.0,
                fair_probability=0.8,
                mark_pnl=55.0 if tail else 0.0,
            )
            row.update({
                "strategy_id": "low_price_tail_capped",
                "strategy_family": "tail_risk_sizing",
                "strategy_status": "candidate",
                "low_price_tail": "True" if tail else "False",
                "tail_risk_bucket": "low_price_tail" if tail else "core_edge",
            })
            rows.append(row)

        payload = build_pnl_payload(
            rows,
            100,
            "taker-20260621-bbe63642",
            "2026-06-21",
            policy_config={"promotion_max_tail_fill_fraction": 0.5},
        )
        strategy = payload["by_strategy"][0]
        alerts = {
            row["code"]
            for row in (payload["tail_fill_quality"]["summary"].get("alerts") or [])
        }

        self.assertEqual(payload["summary"]["settled_order_count"], 0)
        self.assertEqual(payload["summary"]["unsettled_order_count"], 50)
        self.assertGreater(payload["summary"]["mark_to_market_pnl_usdc"], 0)
        self.assertEqual(payload["summary"]["low_price_tail_fill_count"], 31)
        self.assertEqual(payload["tail_fill_quality"]["summary"]["status"], "WARN_HIGH_TAIL_SHARE")
        self.assertIn("HIGH_TAIL_FILL_FRACTION", alerts)
        self.assertIn("TAIL_FILLS_MISSING_SETTLEMENT", alerts)
        self.assertFalse(strategy["quality_candidate_countable"])
        self.assertEqual(strategy["quality_candidate_evidence_basis"], "settlement_scored_executable_after_fee")
        self.assertEqual(strategy["settlement_promotion_gate_status"], "BLOCK")
        self.assertIn("min_settled_orders", strategy["settlement_promotion_failed_gates"])
        self.assertIn("no_unresolved_orders", strategy["settlement_promotion_failed_gates"])
        self.assertIn("max_tail_fill_fraction", strategy["settlement_promotion_failed_gates"])
        self.assertEqual(
            payload["strategy_comparison"]["countable_strategy_quality_candidate_status"],
            "MISSING_SETTLED_SAMPLE",
        )
        self.assertIsNone(payload["strategy_comparison"]["best_settlement_scored_strategy_id"])
        self.assertFalse(payload["strategy_comparison"]["mtm_promotion_allowed"])

    def test_profitability_artifact_verifier_blocks_legacy_taker_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = write_taker_run(
                root,
                "legacy",
                [
                    order_row(
                        "seattle",
                        "highest-temperature-in-seattle-on-june-19-2026",
                        "82-83 F",
                        82,
                        83,
                        10.0,
                        1.0,
                        fair_probability=0.95,
                        mark_pnl=3.0,
                    )
                ],
                reported_net=3.0,
                reported_mtm=3.0,
                reported_unsettled=1,
            )
            (run / "settled_pnl.json").write_text(json.dumps({
                "schema_version": FINALIZATION_SCHEMA_VERSION,
                "summary": {
                    "live_profitability_evidence_basis": "paper_no_fee",
                    "after_fee_pnl_scored": False,
                    "after_slippage_pnl_scored": False,
                    "filled_order_count": 1,
                },
                "pnl": {
                    "summary": {
                        "live_profitability_evidence_basis": "paper_no_fee",
                        "after_fee_pnl_scored": False,
                        "after_slippage_pnl_scored": False,
                        "filled_order_count": 1,
                    },
                    "by_strategy": [
                        {
                            "strategy_id": "legacy",
                            "filled_order_count": 1,
                            "after_fee_pnl_scored": False,
                            "after_slippage_pnl_scored": False,
                        }
                    ],
                },
            }), encoding="utf-8")

            verification = verify_taker_profitability_artifacts(run)

        failed_codes = {
            row["code"]
            for row in verification["checks"]
            if row.get("status") == "FAIL"
        }
        self.assertEqual(verification["status"], "BLOCK")
        self.assertTrue({
            "orders_executable_depth_model_version_missing",
            "orders_executable_depth_model_version_null_only",
        } & failed_codes)
        self.assertIn("strategy_rows_missing", failed_codes)
        self.assertTrue({
            "market_benchmark_no_trade_recommendation_count_missing",
            "market_benchmark_no_trade_recommendation_count_null_only",
        } & failed_codes)
        self.assertIn("finalization_after_fee_pnl_not_scored", failed_codes)
        self.assertIn("finalization_after_slippage_pnl_not_scored", failed_codes)

    def test_profitability_artifact_verifier_passes_fresh_finalized_run_and_bakeoff_records_it(self):
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

            run_folder = Path(payload["run_folder"])
            finalized = finalize_taker_run(run_folder, labels_csv=labels, now="2026-06-20T12:10:00+00:00")
            verification = verify_taker_profitability_artifacts(run_folder)
            bakeoff = run_taker_strategy_bakeoff(
                run_folder,
                labels_csv=labels,
                strategies="raw_edge_control",
                budget_usdc=12,
                out_json=root / "bakeoff.json",
                out_report=root / "bakeoff.md",
                now="2026-06-20T12:20:00+00:00",
            )

        self.assertTrue(finalized["summary"]["after_fee_pnl_scored"])
        self.assertTrue(finalized["summary"]["after_slippage_pnl_scored"])
        self.assertEqual(
            finalized["summary"]["live_profitability_evidence_basis"],
            "executable_after_fee_after_slippage",
        )
        self.assertEqual(verification["status"], "PASS", verification["checks"])
        self.assertEqual(bakeoff["profitability_artifact_verification"]["status"], "PASS")
        self.assertNotIn(
            "profitability_artifact_verification_failed",
            {row["code"] for row in bakeoff["blockers"]},
        )

    def test_strategy_bakeoff_accepts_current_replay_when_source_artifacts_are_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = write_taker_run(
                root,
                "legacy",
                [
                    order_row(
                        "seattle",
                        "highest-temperature-in-seattle-on-june-19-2026",
                        "82-83 F",
                        82,
                        83,
                        10.0,
                        1.0,
                        fair_probability=0.95,
                        mark_pnl=3.0,
                    )
                ],
                reported_net=3.0,
                reported_mtm=3.0,
                reported_unsettled=1,
            )
            labels = root / "market_day_labels.csv"
            write_labels(labels, [
                {
                    "event_slug": "highest-temperature-in-seattle-on-june-19-2026",
                    "market_id": "seattle",
                    "target_date": "2026-06-19",
                    "settlement_bucket": 82,
                    "winning_band": "82-83 F",
                    "quality_grade": "complete",
                }
            ])

            bakeoff = run_taker_strategy_bakeoff(
                run,
                labels_csv=labels,
                strategies="raw_edge_control",
                budget_usdc=100,
                out_json=root / "bakeoff.json",
                out_report=root / "bakeoff.md",
                config={
                    "taker_fee_rate": 0.05,
                    "taker_fee_model": "polymarket_symmetric_price_v1",
                    "max_order_usdc": 10,
                    "max_position_per_token_usdc": 10,
                },
                now="2026-06-20T12:20:00+00:00",
            )

        self.assertEqual(bakeoff["source_profitability_artifact_verification"]["status"], "BLOCK")
        self.assertEqual(bakeoff["current_replay_profitability_verification"]["status"], "PASS")
        self.assertEqual(bakeoff["profitability_artifact_verification"]["status"], "PASS")
        self.assertEqual(
            bakeoff["profitability_artifact_verification"]["evidence_basis"],
            "current_fee_depth_replay",
        )
        self.assertNotIn(
            "profitability_artifact_verification_failed",
            {row["code"] for row in bakeoff["blockers"]},
        )
        self.assertNotIn(
            "profitability_artifact_verification",
            bakeoff["promotion_gates"][0]["failed_gates"],
        )

    def test_profitability_artifact_verifier_allows_no_fill_opportunity_tape(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            run.mkdir()
            write_csv(run / "orders_long.csv", [
                "order_status",
                "fee_usdc",
                "pnl_fee_basis",
                "fee_pnl_usdc",
                "executable_depth_model_version",
                "executable_depth_mode",
                "executable_depth_size",
                "slippage_usdc",
                "executable_net_pnl_usdc",
                "expected_profit_after_friction_per_share",
            ], [
                {
                    "order_status": "SKIPPED",
                    "fee_usdc": 0.0,
                    "pnl_fee_basis": "paper_no_fee",
                    "fee_pnl_usdc": "",
                    "executable_depth_model_version": "top_of_book_only_v1",
                    "executable_depth_mode": "top_of_book",
                    "executable_depth_size": 15.0,
                    "slippage_usdc": "",
                    "executable_net_pnl_usdc": "",
                    "expected_profit_after_friction_per_share": 0.02,
                }
            ])
            (run / "daily_pnl.json").write_text(json.dumps({
                "exchange_economics_gate": {"required": False, "ok": True, "status": "PASS"},
                "summary": {"filled_order_count": 0},
                "by_strategy": [
                    {
                        "strategy_id": "raw_edge_control",
                        "filled_order_count": 0,
                        "after_fee_pnl_scored": False,
                        "after_slippage_pnl_scored": False,
                        "live_profitability_evidence_basis": "paper_no_fee",
                        "market_benchmark_status": "PASS",
                        "market_smarter_slice_count": 0,
                        "market_benchmark_no_trade_net_pnl_usdc": 0.0,
                        "market_benchmark_avoided_loss_usdc": 0.0,
                        "market_benchmark_missed_gain_usdc": 0.0,
                    }
                ],
                "strategy_comparison": {
                    "market_benchmark_summary": {
                        "market_smarter_slice_count": 0,
                        "no_trade_recommendation_count": 1,
                        "avoided_loss_usdc": 0.0,
                        "missed_gain_usdc": 0.0,
                    }
                },
            }), encoding="utf-8")

            verification = verify_taker_profitability_artifacts(run)

        self.assertEqual(verification["status"], "PASS", verification["checks"])
        self.assertIn(
            "orders_realized_profitability_fields_skipped_no_fills",
            {row["code"] for row in verification["checks"] if row.get("status") == "SKIP"},
        )

    def test_recover_run_artifacts_from_orders_preserves_tape_and_passes_profitability_verifier(self):
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
                now=NOW,
                config={"min_edge": 0.05, "max_order_usdc": 10, "max_position_per_token_usdc": 10},
            )
            run_folder = Path(payload["run_folder"])
            orders_path = run_folder / "orders_long.csv"
            original_tape = orders_path.read_text(encoding="utf-8")
            for name in ("daily_pnl.json", "run_config.json", "run_summary.json", "run_report.md", "strategy_summary.json", "strategy_report.md"):
                path = run_folder / name
                if path.exists():
                    path.unlink()

            recovered = recover_run_artifacts_from_orders(
                run_folder,
                budget_usdc=12,
                markets="atlanta",
                snapshots_root=snapshots_root,
                now="2026-06-14T16:05:00+00:00",
                config={"min_edge": 0.05, "max_order_usdc": 10, "max_position_per_token_usdc": 10},
                strategies="raw_edge_control",
            )
            verification = verify_taker_profitability_artifacts(run_folder)

            self.assertEqual(orders_path.read_text(encoding="utf-8"), original_tape)
            self.assertEqual(recovered["summary"]["artifact_recovery"]["status"], "RECOVERED_FROM_ORDERS_TAPE")
            self.assertTrue((run_folder / "daily_pnl.json").exists())
            self.assertTrue((run_folder / "strategy_summary.json").exists())
            self.assertTrue((run_folder / "run_summary.json").exists())
            self.assertEqual(verification["status"], "PASS", verification["checks"])

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
        self.assertAlmostEqual(by_strategy["raw_edge_control"]["spent_usdc"], 10.2)
        self.assertAlmostEqual(by_strategy["small_order_probe"]["spent_usdc"], 1.02)
        self.assertAlmostEqual(by_strategy["raw_edge_control"]["net_pnl_usdc"], 6.466667)
        self.assertAlmostEqual(by_strategy["small_order_probe"]["net_pnl_usdc"], 0.646667)
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

    def test_strategy_bakeoff_accepts_daily_summary_settlement_complete_label(self):
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
                    "settlement_source": "daily_summary",
                    "reconciliation_status": "match",
                }
            ])

            bakeoff = run_taker_strategy_bakeoff(
                source_payload["run_folder"],
                labels_csv=labels,
                strategies="raw_edge_control",
                budget_usdc=12,
                out_json=root / "daily-summary-bakeoff.json",
                out_report=root / "daily-summary-bakeoff.md",
                now="2026-06-20T12:00:00+00:00",
            )

        self.assertFalse(bakeoff["blockers"])
        self.assertEqual(bakeoff["label_summary"]["complete_rows"], 1)
        self.assertEqual(bakeoff["label_summary"]["settlement_complete_rows"], 1)
        self.assertEqual(bakeoff["label_summary"]["snapshot_quality_complete_rows"], 0)
        self.assertEqual(bakeoff["label_summary"]["partial_rows"], 1)
        self.assertEqual(bakeoff["promotion_gates"][0]["status"], "PASS")

    def test_corrupt_newer_strategy_bakeoff_requires_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "run"
            run.mkdir()
            orders = run / "orders_long.csv"
            labels = root / "labels.csv"
            orders.write_text("header\n", encoding="utf-8")
            labels.write_text("header\n", encoding="utf-8")
            os.utime(orders, (1, 1))
            os.utime(labels, (1, 1))

            bakeoff = run / "strategy_bakeoff.json"
            bakeoff.write_text("{", encoding="utf-8")
            os.utime(bakeoff, (2, 2))

            self.assertTrue(bakeoff_needs_refresh(run, labels_csv=labels))

    def test_champion_ledger_blocks_partial_quality_winner_from_dethroning_champion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bakeoff_path = root / "strategy_bakeoff.json"
            bakeoff_path.write_text(json.dumps({
                "schema_version": STRATEGY_BAKEOFF_SCHEMA_VERSION,
                "generated_at_utc": "2026-06-20T12:00:00+00:00",
                "run_id": "daily-bakeoff",
                "source_run_id": "daily",
                "target_date": "2026-06-19",
                "label_summary": {"label_rows": 1, "complete_rows": 0, "partial_rows": 1},
                "blockers": [{"code": "partial_target_date_labels"}],
                "pnl": {
                    "by_strategy": [
                        {
                            "strategy_id": "champion",
                            "strategy_family": "control",
                            "filled_order_count": 1,
                            "settled_order_count": 1,
                            "unsettled_order_count": 0,
                            "unscored_order_count": 0,
                            "spent_usdc": 1,
                            "settlement_pnl_usdc": 1,
                            "net_pnl_usdc": 1,
                        },
                        {
                            "strategy_id": "challenger",
                            "strategy_family": "candidate",
                            "filled_order_count": 1,
                            "settled_order_count": 1,
                            "unsettled_order_count": 0,
                            "unscored_order_count": 0,
                            "spent_usdc": 1,
                            "settlement_pnl_usdc": 10,
                            "net_pnl_usdc": 10,
                        },
                    ]
                },
                "promotion_gates": [
                    {
                        "strategy_id": "champion",
                        "status": "PASS",
                        "settled_order_count": 1,
                        "settled_market_count": 1,
                        "failed_gates": [],
                    },
                    {
                        "strategy_id": "challenger",
                        "status": "PASS",
                        "settled_order_count": 1,
                        "settled_market_count": 1,
                        "failed_gates": [],
                    },
                ],
            }), encoding="utf-8")

            ledger = build_champion_challenger_ledger(
                bakeoff_paths=[bakeoff_path],
                champion_strategy_id="champion",
                now="2026-06-20T12:00:00+00:00",
                min_complete_label_days=1,
                min_settled_orders=1,
            )
            by_strategy = {row["strategy_id"]: row for row in ledger["strategies"]}

        self.assertEqual(ledger["schema_version"], CHAMPION_CHALLENGER_LEDGER_SCHEMA_VERSION)
        self.assertEqual(ledger["promotion_decision"], "KEEP_CHAMPION")
        self.assertEqual(ledger["recommended_strategy_id"], "champion")
        self.assertEqual(by_strategy["challenger"]["promotion_status"], "BLOCK")
        self.assertIn("no_partial_quality_days", by_strategy["challenger"]["failed_gates"])
        self.assertIn("min_complete_label_days", by_strategy["challenger"]["failed_gates"])

    def test_champion_ledger_counts_missing_labels_separately_from_partial_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bakeoff_path = root / "strategy_bakeoff.json"
            bakeoff_path.write_text(json.dumps({
                "schema_version": STRATEGY_BAKEOFF_SCHEMA_VERSION,
                "generated_at_utc": "2026-06-20T12:00:00+00:00",
                "run_id": "daily-bakeoff",
                "source_run_id": "daily",
                "target_date": "2026-06-19",
                "label_summary": {"label_rows": 0, "complete_rows": 0, "partial_rows": 0},
                "blockers": [{"code": "missing_target_date_labels"}],
                "pnl": {
                    "by_strategy": [
                        {
                            "strategy_id": "challenger",
                            "strategy_family": "candidate",
                            "filled_order_count": 1,
                            "settled_order_count": 0,
                            "unsettled_order_count": 1,
                            "unscored_order_count": 0,
                            "spent_usdc": 1,
                            "settlement_pnl_usdc": 0,
                            "net_pnl_usdc": 0,
                        },
                    ]
                },
                "promotion_gates": [
                    {
                        "strategy_id": "challenger",
                        "status": "BLOCK",
                        "settled_order_count": 0,
                        "settled_market_count": 0,
                        "failed_gates": ["min_settled_sample"],
                    },
                ],
            }), encoding="utf-8")

            ledger = build_champion_challenger_ledger(
                bakeoff_paths=[bakeoff_path],
                champion_strategy_id="champion",
                now="2026-06-20T12:00:00+00:00",
                min_complete_label_days=1,
                min_settled_orders=1,
            )
            row = ledger["strategies"][0]

        self.assertEqual(row["partial_quality_day_count"], 0)
        self.assertEqual(row["missing_label_day_count"], 1)
        self.assertIn("no_missing_label_days", row["failed_gates"])
        self.assertNotIn("no_partial_quality_days", row["failed_gates"])

    def test_champion_ledger_does_not_count_no_fill_missing_label_day_as_strategy_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            complete_path = root / "complete_bakeoff.json"
            pending_path = root / "pending_no_fill_bakeoff.json"
            complete_path.write_text(json.dumps({
                "schema_version": STRATEGY_BAKEOFF_SCHEMA_VERSION,
                "generated_at_utc": "2026-06-20T12:00:00+00:00",
                "run_id": "complete-bakeoff",
                "source_run_id": "complete",
                "target_date": "2026-06-19",
                "label_summary": {"label_rows": 1, "complete_rows": 1, "partial_rows": 0},
                "blockers": [],
                "pnl": {
                    "by_strategy": [
                        {
                            "strategy_id": "challenger",
                            "strategy_family": "candidate",
                            "filled_order_count": 1,
                            "settled_order_count": 1,
                            "unsettled_order_count": 0,
                            "unscored_order_count": 0,
                            "spent_usdc": 1,
                            "settlement_pnl_usdc": 2,
                            "net_pnl_usdc": 2,
                        },
                    ]
                },
                "promotion_gates": [
                    {
                        "strategy_id": "challenger",
                        "status": "PASS",
                        "settled_order_count": 1,
                        "settled_market_count": 1,
                        "failed_gates": [],
                    },
                ],
            }), encoding="utf-8")
            pending_path.write_text(json.dumps({
                "schema_version": STRATEGY_BAKEOFF_SCHEMA_VERSION,
                "generated_at_utc": "2026-06-20T12:00:00+00:00",
                "run_id": "pending-bakeoff",
                "source_run_id": "pending",
                "target_date": "2026-06-20",
                "label_summary": {"label_rows": 0, "complete_rows": 0, "partial_rows": 0},
                "blockers": [{"code": "missing_target_date_labels"}],
                "pnl": {
                    "by_strategy": [
                        {
                            "strategy_id": "challenger",
                            "strategy_family": "candidate",
                            "filled_order_count": 0,
                            "settled_order_count": 0,
                            "unsettled_order_count": 0,
                            "unscored_order_count": 0,
                            "spent_usdc": 0,
                            "settlement_pnl_usdc": 0,
                            "net_pnl_usdc": 0,
                        },
                    ]
                },
                "promotion_gates": [
                    {
                        "strategy_id": "challenger",
                        "status": "BLOCK",
                        "settled_order_count": 0,
                        "settled_market_count": 0,
                        "failed_gates": ["min_settled_sample"],
                    },
                ],
            }), encoding="utf-8")

            ledger = build_champion_challenger_ledger(
                bakeoff_paths=[complete_path, pending_path],
                champion_strategy_id="champion",
                now="2026-06-20T12:00:00+00:00",
                min_complete_label_days=1,
                min_settled_orders=1,
            )
            row = ledger["strategies"][0]

        self.assertEqual(row["complete_label_day_count"], 1)
        self.assertEqual(row["missing_label_day_count"], 0)
        self.assertNotIn("no_missing_label_days", row["failed_gates"])
        self.assertNotIn("all_complete_days_pass_strategy_gate", row["failed_gates"])

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
        self.assertTrue(gate["paper_only"])
        self.assertTrue(gate["requalification_required"])
        self.assertEqual(gate["next_action"], "continue_canary_until_complete_labels")
        self.assertEqual(gate["complete_label_sample_count"], 0)
        self.assertEqual(gate["canary_settled_order_count"], 1)

    def test_low_price_tail_no_settlement_high_tail_demotes_after_cutover(self):
        gate = next_run_policy_gate(
            {
                "strategies": [{"strategy_id": "low_price_tail_capped", "net_pnl_usdc": 0.0}],
                "comparison": {
                    "countable_strategy_quality_candidate_status": "MISSING_SETTLED_SAMPLE",
                },
            },
            run_config={
                "active_strategy_id": "low_price_tail_capped",
                "active_strategy_lifecycle": "candidate_canary",
                "active_strategy_canary": {"min_settled_orders": 5, "age_days": 1},
                "policy_config": {
                    "canary_min_settled_orders": 5,
                    "canary_min_complete_label_days": 3,
                    "promotion_max_tail_fill_fraction": 0.5,
                    "canary_missing_settlement_blocks_after_age_days": 1,
                },
            },
            bakeoff={
                "label_summary": {"label_rows": 1, "complete_rows": 0, "partial_rows": 1},
                "blockers": [{"code": "partial_target_date_labels"}],
                "pnl": {"by_strategy": [{"strategy_id": "low_price_tail_capped", "net_pnl_usdc": 0.0}]},
                "promotion_gates": [
                    {
                        "strategy_id": "low_price_tail_capped",
                        "status": "BLOCK",
                        "settled_order_count": 0,
                        "unsettled_order_count": 50,
                        "unscored_order_count": 0,
                        "low_price_tail_fill_fraction": 0.62,
                        "tail_fill_quality_status": "WARN_HIGH_TAIL_SHARE",
                        "failed_gates": [
                            "min_settled_sample",
                            "no_unresolved_orders",
                            "max_tail_fill_fraction",
                        ],
                    }
                ],
            },
        )

        self.assertEqual(gate["status"], "BLOCK")
        self.assertEqual(gate["active_strategy_lifecycle_status"], "blocked")
        self.assertFalse(gate["promotion_eligible"])
        self.assertTrue(gate["paper_only"])
        self.assertEqual(gate["paper_only_reason"], "warn_high_tail_share_missing_settled_sample")
        self.assertTrue(gate["requalification_required"])
        self.assertEqual(gate["requalification_route"], "post_fix_taker_campaign")
        self.assertEqual(gate["demotion_code"], "WARN_HIGH_TAIL_SHARE_MISSING_SETTLED_SAMPLE")
        self.assertEqual(gate["next_action"], "route_to_post_fix_requalification_campaign")
        self.assertIn("WARN_HIGH_TAIL_SHARE", gate["reason"])
        self.assertIn("MISSING_SETTLED_SAMPLE", gate["reason"])

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
                    "bad_tail_no_go_enabled": False,
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
        self.assertTrue(finalized["summary"]["active_strategy_paper_only"])
        self.assertTrue(finalized["summary"]["active_strategy_requalification_required"])
        self.assertEqual(
            finalized["summary"]["active_strategy_next_action"],
            "continue_canary_until_complete_labels",
        )
        self.assertIn("candidate_canary", report)
        self.assertNotIn("promoted_default", report)

    def test_low_price_tail_complete_label_waits_for_operator_review_before_live_size(self):
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
                        "pnl_fee_basis": "after_fee",
                        "failed_gates": [],
                    }
                ],
            },
        )

        self.assertEqual(gate["status"], "PASS")
        self.assertEqual(gate["active_strategy_lifecycle_status"], "candidate_canary")
        self.assertFalse(gate["promotion_eligible"])
        self.assertEqual(gate["next_action"], "operator_review_live_size_change")
        self.assertEqual(gate["complete_label_sample_count"], 1)
        self.assertEqual(gate["canary_settled_order_count"], 2)
        self.assertTrue(gate["paper_only"])
        self.assertEqual(gate["paper_only_reason"], "operator_review_required")
        self.assertTrue(gate["canary_after_fee_evidence"])
        self.assertTrue(gate["operator_review_required"])
        self.assertFalse(gate["operator_review_approved"])
        self.assertEqual(gate["operator_review_reason"], "missing_operator_review")

    def test_low_price_tail_complete_label_promotes_after_operator_review(self):
        gate = next_run_policy_gate(
            {
                "strategies": [{"strategy_id": "low_price_tail_capped", "net_pnl_usdc": 5.0}],
                "comparison": {"best_settlement_scored_strategy_id": "low_price_tail_capped"},
            },
            run_config={
                "active_strategy_id": "low_price_tail_capped",
                "active_strategy_lifecycle": "candidate_canary",
                "active_strategy_canary": {"min_settled_orders": 2, "age_days": 1},
                "operator_review": {
                    "status": "APPROVED",
                    "approved_strategy_id": "low_price_tail_capped",
                    "approved_action": "promote_default",
                    "reviewer": "operator",
                    "reviewed_at_utc": "2026-06-20T12:30:00+00:00",
                },
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
                        "pnl_fee_basis": "after_fee",
                        "failed_gates": [],
                    }
                ],
            },
        )

        self.assertEqual(gate["status"], "PASS")
        self.assertEqual(gate["active_strategy_lifecycle_status"], "promoted_default")
        self.assertTrue(gate["promotion_eligible"])
        self.assertEqual(gate["next_action"], "promote_default")
        self.assertFalse(gate["paper_only"])
        self.assertTrue(gate["operator_review_required"])
        self.assertTrue(gate["operator_review_approved"])
        self.assertEqual(gate["operator_review_reason"], "operator_review_approved")
        self.assertEqual(gate["operator_review_action"], "promote_default")

    def test_low_price_tail_complete_label_without_after_fee_stays_paper_only(self):
        gate = next_run_policy_gate(
            {
                "strategies": [{"strategy_id": "low_price_tail_capped", "net_pnl_usdc": 5.0}],
                "comparison": {"best_settlement_scored_strategy_id": "low_price_tail_capped"},
            },
            run_config={
                "active_strategy_id": "low_price_tail_capped",
                "active_strategy_lifecycle": "candidate_canary",
                "active_strategy_canary": {"min_settled_orders": 2, "age_days": 2},
                "policy_config": {
                    "canary_min_settled_orders": 2,
                    "canary_min_complete_label_days": 1,
                    "canary_require_after_fee_pnl": True,
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
        self.assertEqual(gate["active_strategy_lifecycle_status"], "candidate_canary")
        self.assertFalse(gate["promotion_eligible"])
        self.assertTrue(gate["paper_only"])
        self.assertTrue(gate["requalification_required"])
        self.assertEqual(gate["next_action"], "continue_canary_until_after_fee_scoring")
        self.assertFalse(gate["canary_after_fee_evidence"])

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
            self.assertEqual(
                second["summary"]["last_nonzero_scored_tick"]["row_count"],
                first["summary"]["latest_tick_rows"],
            )
            self.assertEqual(
                second["summary"]["latest_tick_scoring_liveness"]["last_nonzero_scored_tick"]["row_count"],
                first["summary"]["latest_tick_rows"],
            )
            self.assertAlmostEqual(second["summary"]["budget_spent_usdc"], 10.2)
            orders = read_csv(Path(second["orders_path"]))
            self.assertEqual(sum(1 for row in orders if row["order_status"] == "FILLED"), 1)

    def test_restart_does_not_reread_or_rescore_no_trade_day_history(self):
        from weather.market import taker_bot_cli

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
                "config": {
                    "min_edge": 0.99,
                    "counterfactual_tape_enabled": False,
                },
            }
            first = build_run_once(now=NOW, **common)
            tape_path = Path(first["orders_path"])
            tape_before = tape_path.read_bytes()
            cumulative_rows = first["summary"]["cumulative_order_rows"]

            original_score_orders = taker_bot_cli.score_orders
            with (
                patch.object(
                    taker_bot_cli,
                    "read_order_rows",
                    side_effect=AssertionError("ordinary restart reread the full tape"),
                ),
                patch.object(
                    taker_bot_cli,
                    "score_orders",
                    wraps=original_score_orders,
                ) as score_mock,
            ):
                second = build_run_once(now="2026-06-14T16:01:00+00:00", **common)

            scored_batch_sizes = [len(call.args[0]) for call in score_mock.call_args_list]
            tape_after = tape_path.read_bytes()

        self.assertGreater(cumulative_rows, 0)
        self.assertEqual(second["summary"]["cumulative_order_rows"], cumulative_rows)
        self.assertEqual(second["summary"]["latest_tick_rows"], 0)
        self.assertTrue(scored_batch_sizes)
        # Settlement-change detection probes one bounded current group per
        # event.  It must not rescore the cumulative tape.
        self.assertLessEqual(max(scored_batch_sizes), 2)
        self.assertEqual(tape_after, tape_before)
        self.assertEqual(
            second["summary"]["incremental_persistence"]["ordinary_full_history_reads"],
            0,
        )

    def test_incremental_restart_pnl_matches_full_reference_on_growing_tape(self):
        from weather.market import taker_bot_cli

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
                "config": {
                    "min_edge": 0.05,
                    "max_order_usdc": 6,
                    "max_position_per_token_usdc": 100,
                    "counterfactual_tape_enabled": False,
                    "market_centered_warm_tail_guard_enabled": False,
                },
            }
            build_run_once(now=NOW, **common)

            folder = snapshots_root / EVENT
            for name in ("snapshots_long.csv", "clob_features_long.csv", "source_status_long.csv"):
                path = folder / name
                rows = read_csv(path)
                for row in rows:
                    if "snapshot_id" in row:
                        row["snapshot_id"] = "s2"
                    for key in ("captured_at_utc", "fetched_at"):
                        if key in row:
                            row[key] = "2026-06-14T16:00:30+00:00"
                    if "clob_book_captured_at_utc" in row:
                        row["clob_book_captured_at_utc"] = "2026-06-14T16:00:50+00:00"
                write_csv(path, list(rows[0]), rows)

            second = build_run_once(now="2026-06-14T16:01:00+00:00", **common)
            persisted = read_csv(Path(second["orders_path"]))
            reference_rows = taker_bot_cli.score_orders(
                persisted,
                snapshots_root=snapshots_root,
                now="2026-06-14T16:01:00+00:00",
            )
            reference = build_pnl_payload(
                reference_rows,
                12,
                "daily",
                TARGET_DATE,
                now="2026-06-14T16:01:00+00:00",
                policy_config=second["config"],
            )

        for key in (
            "order_rows",
            "filled_order_count",
            "budget_spent_usdc",
            "settled_order_count",
            "settlement_pnl_usdc",
            "net_pnl_usdc",
            "reason_counts",
        ):
            self.assertEqual(second["pnl"]["summary"][key], reference["summary"][key])
        actual_strategy = second["pnl"]["by_strategy"][0]
        reference_strategy = reference["by_strategy"][0]
        for key in (
            "order_rows",
            "filled_order_count",
            "spent_usdc",
            "net_pnl_usdc",
            "settled_order_count",
            "reason_counts",
            "market_benchmark_opportunity_count",
            "market_benchmark_missed_gain_usdc",
        ):
            self.assertEqual(actual_strategy[key], reference_strategy[key])

    def test_incremental_benchmark_refreshes_when_settlement_label_arrives(self):
        from weather.market import taker_bot_cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(root, settled=False)
            common = {
                "target_date": TARGET_DATE,
                "budget_usdc": 12,
                "markets": "atlanta",
                "runs_root": root / "taker_runs",
                "snapshots_root": snapshots_root,
                "run_id": "daily",
                "config": {
                    "min_edge": 0.99,
                    "counterfactual_tape_enabled": False,
                },
            }
            first = build_run_once(now=NOW, **common)
            first_strategy = first["pnl"]["market_benchmark_scoreboard"]["by_strategy"][0]
            first_model_top = first_strategy["model_top_net_pnl_usdc"]

            settlement = {
                "event_slug": EVENT,
                "market_id": "atlanta",
                "settlement_bucket": 80,
                "winning_band": "80-81 F",
                "quality_grade": "complete",
            }
            (snapshots_root / EVENT / "settlement.json").write_text(
                json.dumps(settlement),
                encoding="utf-8",
            )
            second = build_run_once(now="2026-06-15T12:00:00+00:00", **common)
            persisted = read_csv(Path(second["orders_path"]))
            reference_rows = taker_bot_cli.score_orders(
                persisted,
                snapshots_root=snapshots_root,
                now="2026-06-15T12:00:00+00:00",
            )
            reference = taker_bot_cli.market_benchmark_scoreboard(
                reference_rows,
                policy_config=second["config"],
            )
            (snapshots_root / EVENT / "settlement.json").unlink()
            with patch.object(taker_bot_cli, "settlement_for_folder", return_value=None):
                third = build_run_once(now="2026-06-15T12:01:00+00:00", **common)

        refresh = second["summary"]["incremental_persistence"]["benchmark_refresh"]
        actual = second["pnl"]["market_benchmark_scoreboard"]
        self.assertEqual(refresh["status"], "CURRENT")
        self.assertEqual(refresh["changed_event_count"], 1)
        self.assertGreaterEqual(refresh["refreshed_group_count"], 1)
        self.assertEqual(refresh["remaining_group_count"], 0)
        self.assertEqual(actual["summary"], reference["summary"])
        self.assertNotEqual(actual["by_strategy"][0]["model_top_net_pnl_usdc"], first_model_top)
        for key in (
            "opportunity_count",
            "settled_opportunity_count",
            "market_smarter_slice_count",
            "model_beats_market_count",
            "model_beats_no_trade_count",
            "model_top_net_pnl_usdc",
            "market_top_net_pnl_usdc",
            "avoided_loss_usdc",
            "missed_gain_usdc",
        ):
            self.assertEqual(actual["by_strategy"][0][key], reference["by_strategy"][0][key])
        third_refresh = third["summary"]["incremental_persistence"]["benchmark_refresh"]
        self.assertEqual(third_refresh["changed_event_count"], 0)
        self.assertEqual(
            third_refresh["settlement_unavailable_after_finalized_event_count"],
            1,
        )
        self.assertEqual(third["pnl"]["market_benchmark_scoreboard"], actual)

    def test_first_benchmark_signature_closes_settlement_arrival_race(self):
        from weather.market import taker_bot_cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(root, settled=False)
            settlement_path = snapshots_root / EVENT / "settlement.json"
            settlement = {
                "event_slug": EVENT,
                "market_id": "atlanta",
                "settlement_bucket": 80,
                "winning_band": "80-81 F",
                "quality_grade": "complete",
            }
            original_group_payloads = taker_bot_cli._benchmark_group_payloads
            calls = {"count": 0}

            def settle_after_initial_score(rows, policy_config):
                payload = original_group_payloads(rows, policy_config)
                if calls["count"] == 0:
                    settlement_path.write_text(json.dumps(settlement), encoding="utf-8")
                calls["count"] += 1
                return payload

            with patch.object(
                taker_bot_cli,
                "_benchmark_group_payloads",
                side_effect=settle_after_initial_score,
            ):
                payload = build_run_once(
                    TARGET_DATE,
                    budget_usdc=12,
                    markets="atlanta",
                    runs_root=root / "taker_runs",
                    snapshots_root=snapshots_root,
                    run_id="daily",
                    now=NOW,
                    config={
                        "min_edge": 0.99,
                        "counterfactual_tape_enabled": False,
                    },
                )
            persisted = read_csv(Path(payload["orders_path"]))
            reference = taker_bot_cli.market_benchmark_scoreboard(
                taker_bot_cli.score_orders(
                    persisted,
                    snapshots_root=snapshots_root,
                    now=NOW,
                ),
                policy_config=payload["config"],
            )

        refresh = payload["summary"]["incremental_persistence"]["benchmark_refresh"]
        self.assertGreaterEqual(refresh["refreshed_group_count"], 1)
        self.assertEqual(refresh["remaining_group_count"], 0)
        self.assertEqual(payload["pnl"]["market_benchmark_scoreboard"]["summary"], reference["summary"])
        self.assertEqual(
            payload["pnl"]["market_benchmark_scoreboard"]["by_strategy"],
            reference["by_strategy"],
        )

    def test_benchmark_refresh_defers_if_settlement_generation_changes_while_scoring(self):
        from weather.market import taker_bot_cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(root, settled=False)
            common = {
                "target_date": TARGET_DATE,
                "budget_usdc": 12,
                "markets": "atlanta",
                "runs_root": root / "taker_runs",
                "snapshots_root": snapshots_root,
                "run_id": "daily",
                "config": {
                    "min_edge": 0.99,
                    "counterfactual_tape_enabled": False,
                },
            }
            first = build_run_once(now=NOW, **common)
            settlement = {
                "event_slug": EVENT,
                "market_id": "atlanta",
                "settlement_bucket": 80,
                "winning_band": "80-81 F",
                "quality_grade": "complete",
            }
            (snapshots_root / EVENT / "settlement.json").write_text(
                json.dumps(settlement),
                encoding="utf-8",
            )
            original_state = taker_bot_cli._benchmark_settlement_state
            calls = {"count": 0}

            def disappear_after_signature(row, **kwargs):
                state = original_state(row, **kwargs)
                calls["count"] += 1
                return state if calls["count"] == 1 else {"present": False}

            with patch.object(
                taker_bot_cli,
                "_benchmark_settlement_state",
                side_effect=disappear_after_signature,
            ):
                deferred = build_run_once(
                    now="2026-06-15T12:00:00+00:00",
                    **common,
                )
            repaired = build_run_once(
                now="2026-06-15T12:01:00+00:00",
                **common,
            )

        deferred_refresh = deferred["summary"]["incremental_persistence"][
            "benchmark_refresh"
        ]
        self.assertEqual(deferred_refresh["status"], "REFRESH_PENDING")
        self.assertEqual(deferred_refresh["deferred_generation_mismatch_group_count"], 1)
        self.assertEqual(deferred_refresh["remaining_group_count"], 1)
        self.assertEqual(
            deferred["pnl"]["strategy_comparison"]["market_benchmark_status"],
            "BLOCK_REFRESH_PENDING",
        )
        self.assertEqual(
            deferred["pnl"]["market_benchmark_scoreboard"],
            first["pnl"]["market_benchmark_scoreboard"],
        )
        repaired_refresh = repaired["summary"]["incremental_persistence"][
            "benchmark_refresh"
        ]
        self.assertEqual(repaired_refresh["status"], "CURRENT")
        self.assertEqual(repaired_refresh["remaining_group_count"], 0)
        self.assertNotEqual(
            repaired["pnl"]["market_benchmark_scoreboard"]["by_strategy"][0][
                "model_top_net_pnl_usdc"
            ],
            first["pnl"]["market_benchmark_scoreboard"]["by_strategy"][0][
                "model_top_net_pnl_usdc"
            ],
        )

    def test_benchmark_refresh_scores_against_captured_absent_generation(self):
        from weather.market import taker_bot_cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(root, settled=True)
            with patch.object(
                taker_bot_cli,
                "_benchmark_settlement_state",
                return_value={"present": False},
            ):
                payload = build_run_once(
                    TARGET_DATE,
                    budget_usdc=12,
                    markets="atlanta",
                    runs_root=root / "taker_runs",
                    snapshots_root=snapshots_root,
                    run_id="daily",
                    now=NOW,
                    config={
                        "min_edge": 0.99,
                        "counterfactual_tape_enabled": False,
                    },
                )

        refresh = payload["summary"]["incremental_persistence"]["benchmark_refresh"]
        strategy = payload["pnl"]["market_benchmark_scoreboard"]["by_strategy"][0]
        self.assertEqual(refresh["status"], "CURRENT")
        self.assertEqual(refresh["remaining_group_count"], 0)
        self.assertEqual(strategy["settled_opportunity_count"], 0)
        self.assertEqual(strategy["model_top_net_pnl_usdc"], 0.0)
        self.assertEqual(strategy["market_top_net_pnl_usdc"], 0.0)

    def test_pending_tick_recovers_order_tail_and_counterfactual_phase_exactly(self):
        from weather.market.taker_bot_incremental import IncrementalTakerStore

        for crash_phase in (
            "order_tail",
            "counterfactual_append",
            "ledger_complete_before_checkpoint_clear",
        ):
            with self.subTest(crash_phase=crash_phase), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                snapshots_root = write_market_fixture(
                    root,
                    settled=True,
                    bands=[(80, "0.70", "0.60")],
                )
                common = {
                    "target_date": TARGET_DATE,
                    "budget_usdc": 12,
                    "markets": "atlanta",
                    "runs_root": root / "taker_runs",
                    "snapshots_root": snapshots_root,
                    "run_id": "daily",
                    "config": {
                        "min_edge": 0.05,
                        "max_order_usdc": 10,
                        "max_position_per_token_usdc": 10,
                        "market_centered_warm_tail_guard_enabled": False,
                    },
                }
                failed = {"value": False}
                if crash_phase == "order_tail":
                    original = IncrementalTakerStore._ingest

                    def crash_once(store, kind, rows, **kwargs):
                        if (
                            kind == "orders"
                            and kwargs.get("committed_bytes") is not None
                            and not failed["value"]
                        ):
                            failed["value"] = True
                            raise RuntimeError("simulated order checkpoint crash")
                        return original(store, kind, rows, **kwargs)

                    patcher = patch.object(IncrementalTakerStore, "_ingest", new=crash_once)
                elif crash_phase == "counterfactual_append":
                    original = IncrementalTakerStore.append_rows

                    def crash_once(store, kind, path, columns, rows, **kwargs):
                        if kind == "counterfactual" and not failed["value"]:
                            failed["value"] = True
                            raise RuntimeError("simulated counterfactual append crash")
                        return original(store, kind, path, columns, rows, **kwargs)

                    patcher = patch.object(IncrementalTakerStore, "append_rows", new=crash_once)
                else:
                    original = IncrementalTakerStore.clear_pending_tick

                    def crash_once(store):
                        if not failed["value"]:
                            failed["value"] = True
                            raise RuntimeError("simulated pending checkpoint-clear crash")
                        return original(store)

                    patcher = patch.object(
                        IncrementalTakerStore,
                        "clear_pending_tick",
                        new=crash_once,
                    )

                with patcher, self.assertRaisesRegex(RuntimeError, "simulated"):
                    build_run_once(now=NOW, **common)

                run_folder = root / "taker_runs" / TARGET_DATE / "daily"
                with IncrementalTakerStore(run_folder) as staged:
                    pending = staged.pending_tick()
                    self.assertTrue(pending.get("order_rows"))
                    self.assertTrue(pending.get("counterfactual_rows"))
                    pending_tick_id = pending["incremental_tick_id"]
                    pending_budget_ledger_count = len(pending.get("budget_ledger") or [])
                    pending_counterfactual_ledger_count = len(
                        pending.get("counterfactual_ledger") or []
                    )

                recovered = build_run_once(
                    now="2026-06-14T16:01:00+00:00",
                    **common,
                )
                orders = read_csv(Path(recovered["orders_path"]))
                counterfactual = read_csv(Path(recovered["counterfactual_orders_path"]))
                budget_ledger = [
                    json.loads(line)
                    for line in Path(recovered["budget_ledger_path"]).read_text(
                        encoding="utf-8"
                    ).splitlines()
                    if line.strip()
                ]
                counterfactual_ledger = [
                    json.loads(line)
                    for line in Path(recovered["counterfactual_budget_ledger_path"]).read_text(
                        encoding="utf-8"
                    ).splitlines()
                    if line.strip()
                ]
                with IncrementalTakerStore(run_folder) as store:
                    pending_after = store.pending_tick()
                    benchmark_pending = store.benchmark_pending_count("orders")

                self.assertTrue(
                    recovered["summary"]["incremental_persistence"]["pending_tick_recovery"][
                        "recovered"
                    ]
                )
                self.assertEqual(
                    len({row["intent_key"] for row in orders}),
                    len(orders),
                )
                self.assertEqual(
                    len({row["intent_key"] for row in counterfactual}),
                    len(counterfactual),
                )
                self.assertTrue(
                    any(
                        row["real_order_status"] != "NOT_SELECTED"
                        and row["real_strategy_id"]
                        for row in counterfactual
                    )
                )
                self.assertEqual(pending_after, {})
                self.assertEqual(benchmark_pending, 0)
                self.assertEqual(
                    sum(
                        row.get("incremental_tick_id") == pending_tick_id
                        for row in budget_ledger
                    ),
                    pending_budget_ledger_count,
                )
                self.assertEqual(
                    sum(
                        row.get("incremental_tick_id") == pending_tick_id
                        for row in counterfactual_ledger
                    ),
                    pending_counterfactual_ledger_count,
                )

    def test_fresh_archives_old_generation_and_restarts_checkpoint_cleanly(self):
        from weather.market.taker_bot_incremental import STATE_FILENAME

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root = root / "taker_runs"
            snapshots_root = write_market_fixture(root, settled=True)
            common = {
                "target_date": TARGET_DATE,
                "budget_usdc": 12,
                "markets": "atlanta",
                "runs_root": runs_root,
                "snapshots_root": snapshots_root,
                "run_id": "daily",
                "config": {"counterfactual_tape_enabled": False},
            }
            original = build_run_once(now=NOW, **common)
            original_tape = Path(original["orders_path"]).read_bytes()
            original_checkpoint = Path(original["run_folder"]) / STATE_FILENAME
            self.assertTrue(original_checkpoint.exists())

            fresh = build_run_once(
                now="2026-06-14T16:01:00+00:00",
                append=False,
                **common,
            )
            archive = Path(
                fresh["summary"]["incremental_persistence"]["fresh_archive_path"]
            )
            active_folder = Path(fresh["run_folder"])
            fresh_row_count = len(read_csv(Path(fresh["orders_path"])))
            self.assertTrue(archive.exists())
            self.assertNotIn(runs_root, archive.parents)
            self.assertEqual((archive / "orders_long.csv").read_bytes(), original_tape)
            self.assertTrue((archive / STATE_FILENAME).exists())
            self.assertFalse((active_folder / STATE_FILENAME).exists())

            resumed = build_run_once(
                now="2026-06-14T16:02:00+00:00",
                **common,
            )
            resumed_checkpoint_exists = Path(resumed["run_folder"], STATE_FILENAME).exists()

        self.assertEqual(resumed["summary"]["cumulative_order_rows"], fresh_row_count)
        self.assertEqual(resumed["summary"]["latest_tick_rows"], 0)
        self.assertTrue(resumed_checkpoint_exists)
        self.assertEqual(
            resumed["summary"]["incremental_persistence"]["recovery_kind"],
            "legacy_full_stream",
        )

    def test_incremental_no_side_runtime_payload_keeps_canonical_slices_and_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                bands=[(80, "0.30", "0.60")],
                include_no_book=True,
            )
            common = {
                "target_date": TARGET_DATE,
                "budget_usdc": 12,
                "markets": "atlanta",
                "runs_root": root / "taker_runs",
                "snapshots_root": snapshots_root,
                "run_id": "daily",
                "strategies": "fade_overpriced",
                "config": {
                    "min_edge": 0.05,
                    "max_order_usdc": 10,
                    "max_position_per_token_usdc": 10,
                    "market_centered_warm_tail_guard_enabled": False,
                    "counterfactual_tape_enabled": False,
                },
            }
            first = build_run_once(
                now=NOW,
                **{
                    **common,
                    "config": {
                        **common["config"],
                        "counterfactual_tape_enabled": True,
                    },
                },
            )
            second = build_run_once(now="2026-06-14T16:01:00+00:00", **common)

        campaign = second["summary"]["no_side_campaign"]
        pnl_strategy = second["pnl"]["by_strategy"][0]
        self.assertEqual(first["summary"]["no_side_campaign"]["by_market"], campaign["by_market"])
        self.assertTrue(campaign["by_market"])
        self.assertTrue(campaign["by_hour"])
        self.assertEqual(
            campaign["slices"],
            {"by_market": campaign["by_market"], "by_hour": campaign["by_hour"]},
        )
        strategy = campaign["by_strategy"][0]
        self.assertEqual(strategy["strategy_id"], "fade_overpriced")
        self.assertEqual(
            strategy["strategy_market_top_net_pnl_usdc"],
            pnl_strategy["market_benchmark_market_top_net_pnl_usdc"],
        )
        self.assertEqual(
            strategy["settlement_promotion_gate_status"],
            pnl_strategy["settlement_promotion_gate_status"],
        )
        self.assertEqual(
            strategy["settlement_promotion_failed_gates"],
            pnl_strategy["settlement_promotion_failed_gates"],
        )
        first_counterfactual = first["summary"]["counterfactual_no_side_campaign"]
        second_counterfactual = second["summary"]["counterfactual_no_side_campaign"]
        self.assertGreater(first_counterfactual["no_side_would_buy_count"], 0)
        for key in (
            "no_side_would_buy_count",
            "settled_no_side_would_buy_count",
            "no_side_net_pnl_usdc",
            "countable_no_side_net_pnl_usdc",
            "by_market",
            "by_hour",
        ):
            self.assertEqual(second_counterfactual[key], first_counterfactual[key])

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
            self.assertAlmostEqual(pnl["mark_to_market_pnl_usdc"], 1.8)
            self.assertAlmostEqual(payload["summary"]["cumulative_net_pnl_usdc"], 1.8)

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

    def test_finalization_watchdog_finalizes_labelable_run_with_missing_settled_pnl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = write_taker_run(
                root,
                "taker-20260619-watchdog",
                [
                    order_row(
                        "atlanta",
                        "highest-temperature-in-atlanta-on-june-19-2026",
                        "88-89 F",
                        88,
                        89,
                        54.76,
                        11.73047,
                    )
                ],
                reported_net=0,
                reported_mtm=0,
                reported_unsettled=1,
            )
            labels = root / "market_day_labels.csv"
            write_labels(labels, [
                {
                    "event_slug": "highest-temperature-in-atlanta-on-june-19-2026",
                    "market_id": "atlanta",
                    "target_date": "2026-06-19",
                    "settlement_bucket": 88,
                    "winning_band": "88-89 F",
                    "quality_grade": "complete",
                }
            ])
            os.utime(labels, (1, 1))

            payload = finalization_watchdog(
                target_date="2026-06-19",
                runs_root=root / "taker_runs",
                labels_csv=labels,
                now="2026-06-20T12:00:00+00:00",
                sla_hours=1,
                min_free_bytes=0,
            )

            self.assertEqual(payload["summary"]["finalized_run_count"], 1)
            self.assertEqual(payload["summary"]["sla_breach_count"], 0)
            self.assertEqual(payload["summary"]["bakeoff_created_count"], 1)
            self.assertTrue((run / "settled_pnl.json").exists())
            self.assertTrue((run / "strategy_bakeoff.json").exists())
            settled = json.loads((run / "settled_pnl.json").read_text(encoding="utf-8"))
            self.assertTrue(settled["next_run_policy_gate"]["bakeoff_available"])
            self.assertEqual(payload["runs"][0]["status"], "FINALIZED")
            self.assertEqual(payload["runs"][0]["sla_status"], "PASS")
            self.assertEqual(payload["runs"][0]["bakeoff_action"], "created")
            self.assertEqual(payload["runs"][0]["action"], "finalized")

    def test_finalize_taker_run_uses_current_exchange_economics_snapshot_when_supplied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = write_taker_run(
                root,
                "taker-20260619-current-exchange-proof",
                [
                    order_row(
                        "atlanta",
                        "highest-temperature-in-atlanta-on-june-19-2026",
                        "88-89 F",
                        88,
                        89,
                        54.76,
                        11.73047,
                    )
                ],
                reported_net=0,
                reported_mtm=0,
                reported_unsettled=1,
            )
            stale_gate = {
                "required": True,
                "ok": False,
                "status": "BLOCK",
                "reason": "stale fixture",
                "snapshot_id": "xecon-stale",
                "snapshot_hash": "stale-hash",
                "evidence_basis": exchange_economics.STALE_EVIDENCE_BASIS,
                "verified_for_target_date": "2026-06-18",
                "verified_at_utc": "2026-06-18T12:00:00+00:00",
            }
            (run / "run_config.json").write_text(
                json.dumps({"exchange_economics_gate": stale_gate}),
                encoding="utf-8",
            )
            snapshot_path = root / "exchange_economics_snapshot.json"
            snapshot = exchange_economics.build_snapshot_payload(
                target_date="2026-06-19",
                verified_at_utc="2026-06-20T12:00:00+00:00",
            )
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
            labels = root / "market_day_labels.csv"
            write_labels(labels, [
                {
                    "event_slug": "highest-temperature-in-atlanta-on-june-19-2026",
                    "market_id": "atlanta",
                    "target_date": "2026-06-19",
                    "settlement_bucket": 88,
                    "winning_band": "88-89 F",
                    "quality_grade": "complete",
                }
            ])

            finalized = finalize_taker_run(
                run,
                labels_csv=labels,
                now="2026-06-20T12:00:00+00:00",
                exchange_economics_snapshot_path=snapshot_path,
                exchange_economics_required=True,
            )

            expected_hash = exchange_economics.snapshot_hash(snapshot)
            self.assertEqual(finalized["exchange_economics_gate"]["status"], "PASS")
            self.assertEqual(finalized["exchange_economics_gate"]["verified_for_target_date"], "2026-06-19")
            self.assertEqual(finalized["summary"]["exchange_economics_gate_status"], "PASS")
            self.assertEqual(finalized["summary"]["exchange_economics_hash"], expected_hash)
            self.assertNotEqual(finalized["next_run_policy_gate"]["status"], "BLOCK")
            self.assertEqual(finalized["next_run_policy_gate"]["exchange_economics_status"], "PASS")
            self.assertEqual(finalized["next_run_policy_gate"]["exchange_economics_hash"], expected_hash)
            strategy_summary = json.loads((run / "settled_strategy_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(strategy_summary["exchange_economics_status"], "PASS")
            self.assertEqual(
                strategy_summary["exchange_economics_evidence_basis"],
                exchange_economics.CURRENT_EVIDENCE_BASIS,
            )
            self.assertEqual(strategy_summary["exchange_economics_hash"], expected_hash)
            settled_rows = read_csv(run / "settled_orders_long.csv")
            self.assertEqual(
                settled_rows[0]["exchange_economics_evidence_basis"],
                exchange_economics.CURRENT_EVIDENCE_BASIS,
            )
            self.assertEqual(settled_rows[0]["exchange_economics_hash"], expected_hash)

    def test_finalization_watchdog_refinalizes_stale_exchange_economics_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = write_taker_run(
                root,
                "taker-20260619-refresh-exchange-proof",
                [
                    order_row(
                        "atlanta",
                        "highest-temperature-in-atlanta-on-june-19-2026",
                        "88-89 F",
                        88,
                        89,
                        54.76,
                        11.73047,
                    )
                ],
                reported_net=0,
                reported_mtm=0,
                reported_unsettled=1,
            )
            stale_gate = {
                "required": True,
                "ok": False,
                "status": "BLOCK",
                "reason": "stale fixture",
                "snapshot_id": "xecon-stale",
                "snapshot_hash": "stale-hash",
                "evidence_basis": exchange_economics.STALE_EVIDENCE_BASIS,
                "verified_for_target_date": "2026-06-18",
                "verified_at_utc": "2026-06-18T12:00:00+00:00",
            }
            (run / "run_config.json").write_text(
                json.dumps({"exchange_economics_gate": stale_gate}),
                encoding="utf-8",
            )
            labels = root / "market_day_labels.csv"
            write_labels(labels, [
                {
                    "event_slug": "highest-temperature-in-atlanta-on-june-19-2026",
                    "market_id": "atlanta",
                    "target_date": "2026-06-19",
                    "settlement_bucket": 88,
                    "winning_band": "88-89 F",
                    "quality_grade": "complete",
                }
            ])
            finalized = finalize_taker_run(run, labels_csv=labels, now="2026-06-20T12:00:00+00:00")
            self.assertEqual(finalized["summary"]["exchange_economics_gate_status"], "BLOCK")
            snapshot_path = root / "exchange_economics_snapshot.json"
            snapshot = exchange_economics.build_snapshot_payload(
                target_date="2026-06-19",
                verified_at_utc="2026-06-20T12:00:00+00:00",
            )
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

            payload = finalization_watchdog(
                target_date="2026-06-19",
                runs_root=root / "taker_runs",
                labels_csv=labels,
                now="2026-06-20T12:00:00+00:00",
                min_free_bytes=0,
                ensure_bakeoff=False,
                exchange_economics_snapshot_path=snapshot_path,
                exchange_economics_required=True,
            )

            expected_hash = exchange_economics.snapshot_hash(snapshot)
            self.assertEqual(payload["summary"]["finalized_run_count"], 1)
            self.assertEqual(payload["runs"][0]["exchange_economics_finalization_status"], "CURRENT")
            refreshed = json.loads((run / "settled_strategy_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(refreshed["exchange_economics_status"], "PASS")
            self.assertEqual(refreshed["exchange_economics_hash"], expected_hash)

    def test_finalization_watchdog_blocks_labelable_run_when_disk_preflight_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = write_taker_run(
                root,
                "taker-20260619-disk-blocked",
                [
                    order_row(
                        "atlanta",
                        "highest-temperature-in-atlanta-on-june-19-2026",
                        "88-89 F",
                        88,
                        89,
                        54.76,
                        11.73047,
                    )
                ],
                reported_net=0,
                reported_mtm=0,
                reported_unsettled=1,
            )
            labels = root / "market_day_labels.csv"
            write_labels(labels, [
                {
                    "event_slug": "highest-temperature-in-atlanta-on-june-19-2026",
                    "market_id": "atlanta",
                    "target_date": "2026-06-19",
                    "settlement_bucket": 88,
                    "winning_band": "88-89 F",
                    "quality_grade": "complete",
                }
            ])
            os.utime(labels, (1, 1))

            payload = finalization_watchdog(
                target_date="2026-06-19",
                runs_root=root / "taker_runs",
                labels_csv=labels,
                now="2026-06-20T12:00:00+00:00",
                sla_hours=1,
                min_free_bytes=100,
                disk_usage_fn=lambda _path: SimpleNamespace(total=1000, used=950, free=50),
            )

            self.assertEqual(payload["summary"]["finalized_run_count"], 0)
            self.assertEqual(payload["summary"]["sla_breach_count"], 1)
            self.assertFalse((run / "settled_pnl.json").exists())
            self.assertEqual(payload["runs"][0]["status"], "DISK_BLOCKED_FINALIZATION")
            self.assertEqual(payload["runs"][0]["bakeoff_action"], "blocked_disk_capacity")
            self.assertEqual(payload["runs"][0]["action"], "blocked_disk_capacity")
            self.assertEqual(payload["disk_capacity_preflight"]["status"], "LOW_SPACE")

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
                config={"bad_tail_no_go_enabled": False},
            )
            gate = bakeoff["promotion_gates"][0]

        self.assertEqual(bakeoff["schema_version"], STRATEGY_BAKEOFF_SCHEMA_VERSION)
        self.assertEqual(gate["status"], "BLOCK")
        self.assertIn("non_negative_settled_roi", gate["failed_gates"])
        self.assertIn("no_resolved_stale_mark_sign_flips", gate["failed_gates"])
        self.assertEqual(gate["stale_mark_sign_flip_count"], 1)
        self.assertAlmostEqual(gate["net_pnl_usdc"], -8.9216)

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
        self.assertTrue(any(row["reason_code"] == "NO_TRADE_CURRENT_HIGH_TRUST_GATE" for row in orders))
        self.assertTrue(all(row["order_status"] != "FILLED" for row in orders))

    def test_current_high_trust_gate_blocks_pre_late_aggressive_taker(self):
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
                config={
                    "min_edge": 0.05,
                    "max_order_usdc": 10,
                    "max_position_per_token_usdc": 10,
                    "early_hour_block_guarded_current_high": False,
                },
            )
            orders = read_csv(Path(payload["orders_path"]))

        self.assertEqual(payload["summary"]["latest_tick_filled_orders"], 0)
        self.assertTrue(any(row["reason_code"] == "NO_TRADE_CURRENT_HIGH_TRUST_GATE" for row in orders))
        blocked = [row for row in orders if row["reason_code"] == "NO_TRADE_CURRENT_HIGH_TRUST_GATE"]
        self.assertTrue(all(row["current_high_trust_gate_action"] == "deny_aggressive" for row in blocked))

    def test_weak_slot_gate_allows_permissioned_raw_edge_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                captured_at="2026-06-14T13:30:00+00:00",
                book_captured_at="2026-06-14T13:30:10+00:00",
                bands=[(80, "0.70", "0.10")],
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

        self.assertEqual(payload["summary"]["latest_tick_filled_orders"], 1)
        self.assertEqual(payload["summary"]["weak_slot_blocked_rows"], 0)
        self.assertTrue(any(row["weak_slot_gate_status"] == "permissioned" for row in orders))
        self.assertFalse(any(row["reason_code"] == "NO_TRADE_WEAK_SLOT_KILL_SWITCH" for row in orders))

    def test_weak_slot_gate_blocks_unpermissioned_candidate_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                captured_at="2026-06-14T13:30:00+00:00",
                book_captured_at="2026-06-14T13:30:10+00:00",
                bands=[(80, "0.70", "0.10")],
                snapshot_extra_fields_by_value={
                    80: {
                        "taker_edge_permission": "deny",
                        "taker_edge_permission_reason": "fixture_unproven_weak_slot",
                        "taker_skill_weight": "0.0",
                    }
                },
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
                strategies="low_price_tail_capped",
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
        self.assertTrue(any(row["strategy_id"] == "low_price_tail_capped" for row in orders))
        blocked = [row for row in orders if row["reason_code"] == "NO_TRADE_WEAK_SLOT_KILL_SWITCH"]
        self.assertEqual(len(blocked), 1)
        self.assertIn("edge_permission:deny", blocked[0]["weak_slot_gate_reason"])

    def test_weak_slot_explicit_star_kill_switch_blocks_permissioned_slice(self):
        state = weak_slot_gate_state(
            {
                "market_id": "atlanta",
                "event_slug": EVENT,
                "captured_at_utc": "2026-06-14T13:30:00+00:00",
                "strategy_family": "raw_edge",
                "taker_edge_permission": "edge_allowed",
            },
            {
                **DEFAULT_CONFIG,
                "_weak_slot_gate_status": "BLOCK",
                "_weak_slot_minutes": [570],
                "weak_slot_guard_block_strategy_families": "*",
            },
        )

        self.assertEqual(state["weak_slot_gate_status"], "blocked")
        self.assertIn("operator_kill_switch", state["weak_slot_gate_reason"])

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

    def test_market_centered_warm_tail_guard_blocks_unpermissioned_candidate_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                bands=[(80, "0.30", "0.28"), (84, "0.70", "0.10")],
                snapshot_extra_fields_by_value={
                    84: {
                        "taker_edge_permission": "deny",
                        "taker_edge_permission_reason": "fixture_unproven_warm_tail",
                        "taker_skill_weight": "0.0",
                    }
                },
            )

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=12,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now=NOW,
                strategies="low_price_tail_capped",
                config={
                    "min_edge": 0.05,
                    "max_order_usdc": 10,
                    "max_position_per_token_usdc": 10,
                    "market_centered_warm_tail_require_clob_continuity": False,
                },
            )
            orders = read_csv(Path(payload["orders_path"]))

        warm_rows = [row for row in orders if row["range_label"] == "84-85 F"]
        self.assertEqual(payload["summary"]["latest_tick_filled_orders"], 0)
        self.assertEqual(warm_rows[0]["strategy_id"], "low_price_tail_capped")
        self.assertEqual(warm_rows[0]["reason_code"], "NO_TRADE_MARKET_CENTERED_WARM_TAIL")
        self.assertIn("edge_permission:deny", warm_rows[0]["warm_tail_guard_reason"])

    def test_market_centered_warm_tail_guard_allows_permissioned_candidate_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = write_market_fixture(
                root,
                settled=True,
                bands=[(80, "0.30", "0.28"), (84, "0.70", "0.10")],
            )

            payload = build_run_once(
                TARGET_DATE,
                budget_usdc=12,
                markets="atlanta",
                runs_root=root / "taker_runs",
                snapshots_root=snapshots_root,
                run_id="daily",
                now=NOW,
                strategies="low_price_tail_capped",
                config={
                    "min_edge": 0.05,
                    "max_order_usdc": 10,
                    "max_position_per_token_usdc": 10,
                    "market_centered_warm_tail_require_clob_continuity": False,
                },
            )
            orders = read_csv(Path(payload["orders_path"]))

        warm_rows = [row for row in orders if row["range_label"] == "84-85 F"]
        filled = [row for row in warm_rows if row["order_status"] == "FILLED"]
        self.assertEqual(payload["summary"]["market_centered_warm_tail_blocked_rows"], 0)
        self.assertEqual(len(filled), 1)
        self.assertEqual(filled[0]["warm_tail_guard_status"], "active")
        self.assertEqual(filled[0]["bad_tail_no_go_status"], "inactive")

    def test_market_centered_warm_tail_explicit_star_kill_switch_blocks_permissioned_slice(self):
        state = warm_tail_guard_state(
            {
                "strategy_family": "tail_risk_sizing",
                "strategy_status": "candidate",
                "taker_edge_permission": "edge_allowed",
                "market_centered_warm_tail": True,
                "market_modal_band_distance": "3",
                "market_modal_band_key": "eq:80-81",
                "clob_continuity_status": "pass",
                "risk_adjusted_edge": "0.50",
            },
            {**DEFAULT_CONFIG, "market_centered_warm_tail_block_strategy_families": "*"},
        )

        self.assertEqual(state["warm_tail_guard_status"], "blocked")
        self.assertIn("operator_kill_switch", state["warm_tail_guard_reason"])

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
        self.assertAlmostEqual(payload["summary"]["budget_spent_usdc"], 2.04)

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

    def test_correlated_regime_cap_shrinks_then_blocks_same_regime_taker_exposure(self):
        def row_for(market_id):
            return {
                "market_id": market_id,
                "event_slug": f"highest-temperature-in-{market_id}-on-june-14-2026",
                "snapshot_id": "s1",
                "captured_at_utc": NOW,
                "range_label": "84-85 F",
                "bin_kind": "eq",
                "bin_value": "84",
                "bin_value_hi": "85",
                "condition_id": f"condition-{market_id}",
                "clob_token_id": f"token-{market_id}",
                "fair_probability": "0.80",
                "calibrated_fair_probability": "0.80",
                "taker_skill_weight": "1.0",
                "clob_best_bid": "0.49",
                "clob_best_ask": "0.50",
                "best_ask": "0.50",
                "market_mid": "0.50",
                "ask_size_at_best": "20",
                "ask_depth_1pct": "20",
                "min_order_size": "1",
                "market_status": "active",
                "source_fresh": True,
                "source_freshness_state": "all_fresh",
                "snapshot_cadence": "scheduled",
                "current_high_trusted": True,
                "settlement_current_high": "80",
            }

        now = datetime.fromisoformat(NOW).astimezone(timezone.utc)
        rows, _ledger = apply_taker_budget(
            [row_for("atlanta"), row_for("miami")],
            [],
            budget_usdc=20,
            run_id="daily",
            target_date=TARGET_DATE,
            now=now,
            config={
                **DEFAULT_CONFIG,
                "min_edge": 0.05,
                "max_order_usdc": 6.0,
                "max_position_per_token_usdc": 6.0,
                "max_correlated_regime_notional_usdc": 5.0,
                "max_correlated_regime_joint_loss_usdc": 5.0,
                "taker_fee_rate": 0.0,
                "taker_edge_permission_enabled": False,
                "calibrated_entry_enabled": False,
                "calibrated_sizing_enabled": False,
                "market_centered_warm_tail_guard_enabled": False,
                "bad_tail_no_go_enabled": False,
            },
        )

        filled = [row for row in rows if row["order_status"] == "FILLED"]
        blocked = [row for row in rows if row["reason_code"] == "NO_TRADE_CORRELATED_REGIME_EXPOSURE_CAP"]

        self.assertEqual(len(filled), 1)
        self.assertEqual(len(blocked), 1)
        self.assertEqual(filled[0]["correlated_regime_group_key"], "2026-06-14|southeast|warm")
        self.assertEqual(blocked[0]["correlated_regime_group_key"], filled[0]["correlated_regime_group_key"])
        self.assertAlmostEqual(float(filled[0]["fill_notional_usdc"]), 5.0)
        self.assertAlmostEqual(float(filled[0]["correlated_regime_joint_stress_loss_after_usdc"]), 5.0)
        self.assertTrue(blocked[0]["correlated_regime_cap_breached"])


if __name__ == "__main__":
    unittest.main()
