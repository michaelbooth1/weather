import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from mm_risk import (  # noqa: E402
    BalanceState,
    InventoryLeg,
    SizingConfig,
    SizingState,
    balance_available,
    event_inventory_metrics,
    reserve_order,
    risk_halt_decision,
    sizing_decision,
    negative_risk_apply_fill,
    negative_risk_cancel_all,
    negative_risk_convert_complete_sets,
    negative_risk_initial_state,
    negative_risk_place_order,
    negative_risk_reduce_order,
    negative_risk_settle,
    negative_risk_summary,
)


class TestMarketMakingRisk(unittest.TestCase):
    def test_event_inventory_metrics_scores_pnl_by_settlement_outcome(self):
        legs = [
            InventoryLeg(outcome="80-81", side="YES", shares=10.0, avg_price=0.40),
            InventoryLeg(outcome="82-83", side="NO", shares=5.0, avg_price=0.30),
        ]

        metrics = event_inventory_metrics(
            outcomes=["80-81", "82-83", "84-85"],
            probabilities={"80-81": 0.50, "82-83": 0.30, "84-85": 0.20},
            legs=legs,
            negative_risk_conversion_state="simulated_only",
        )

        self.assertAlmostEqual(metrics["pnl_by_outcome"]["80-81"], 9.5)
        self.assertAlmostEqual(metrics["pnl_by_outcome"]["82-83"], -5.5)
        self.assertAlmostEqual(metrics["pnl_by_outcome"]["84-85"], -0.5)
        self.assertAlmostEqual(metrics["expected_value"], 3.0)
        self.assertAlmostEqual(metrics["worst_case_loss"], 5.5)
        self.assertEqual(metrics["negative_risk_conversion_state"], "simulated_only")

    def test_sizing_stack_uses_zero_kelly_until_edge_is_credible(self):
        decision = sizing_decision(
            side="YES_BID",
            price=0.40,
            fair_probability=0.60,
            config=SizingConfig(
                rewards_min_size_or_target=5.0,
                per_band_cap_usdc=100.0,
                per_event_expected_loss_cap_usdc=100.0,
                per_event_worst_case_cap_usdc=100.0,
                daily_drawdown_budget_usdc=100.0,
                fractional_kelly=0.25,
                available_backed_balance_usdc=100.0,
                live_edge_is_credible=False,
            ),
        )

        self.assertEqual(decision["size"], 0.0)
        self.assertEqual(decision["final_size_limiter"], "fractional_kelly_cap")
        self.assertEqual(decision["kelly_fraction"], 0.0)

    def test_sizing_stack_reports_binding_cap_after_kelly_enabled(self):
        decision = sizing_decision(
            side="YES_BID",
            price=0.50,
            fair_probability=0.70,
            config=SizingConfig(
                rewards_min_size_or_target=50.0,
                per_band_cap_usdc=4.0,
                per_event_expected_loss_cap_usdc=100.0,
                per_event_worst_case_cap_usdc=100.0,
                daily_drawdown_budget_usdc=100.0,
                fractional_kelly=0.25,
                available_backed_balance_usdc=100.0,
                live_edge_is_credible=True,
            ),
            state=SizingState(current_band_notional_usdc=1.0),
        )

        self.assertAlmostEqual(decision["kelly_fraction"], 0.4)
        self.assertAlmostEqual(decision["size"], 6.0)
        self.assertEqual(decision["final_size_limiter"], "per_band_cap")
        self.assertAlmostEqual(decision["risk_usdc"], 3.0)

    def test_sizing_stack_caps_yes_ask_by_no_side_risk(self):
        decision = sizing_decision(
            side="YES_ASK",
            price=0.75,
            fair_probability=0.40,
            config=SizingConfig(
                rewards_min_size_or_target=50.0,
                per_band_cap_usdc=100.0,
                per_event_expected_loss_cap_usdc=100.0,
                per_event_worst_case_cap_usdc=2.0,
                daily_drawdown_budget_usdc=100.0,
                fractional_kelly=0.25,
                available_backed_balance_usdc=100.0,
                live_edge_is_credible=True,
            ),
        )

        self.assertEqual(decision["final_size_limiter"], "per_event_worst_case_cap")
        self.assertAlmostEqual(decision["size"], 8.0)
        self.assertAlmostEqual(decision["risk_usdc"], 2.0)

    def test_risk_halt_decision_fails_closed_on_any_halt(self):
        decision = risk_halt_decision(
            stale_source_halt=True,
            stale_book_halt=True,
            heartbeat_halt=False,
        )

        self.assertFalse(decision["quote_permission"])
        self.assertTrue(decision["halted"])
        self.assertEqual(decision["primary_reason"], "stale_source_halt")
        self.assertEqual(
            [reason["reason"] for reason in decision["reasons"]],
            ["stale_source_halt", "stale_book_halt"],
        )

    def test_balance_reservation_accounts_for_open_orders_and_allowance(self):
        state = BalanceState(
            backed_balance_usdc=100.0,
            open_order_reserves_usdc=30.0,
            pending_allowance_usdc=5.0,
            negative_risk_conversion_state="not_verified",
        )

        self.assertAlmostEqual(balance_available(state), 65.0)
        reservation = reserve_order(state, 80.0)

        self.assertFalse(reservation["accepted"])
        self.assertAlmostEqual(reservation["reserved_usdc"], 65.0)
        self.assertAlmostEqual(reservation["available_after_usdc"], 0.0)
        self.assertEqual(reservation["negative_risk_conversion_state"], "not_verified")

    def test_negative_risk_lifecycle_tracks_partial_fills_reductions_and_settlement(self):
        state = negative_risk_initial_state(
            100.0,
            ["80-81", "82-83", "84-85"],
            negative_risk_conversion_state="simulated_only",
        )
        state = negative_risk_place_order(state, "o1", "80-81", "YES_BID", 0.40, 10.0)
        state = negative_risk_place_order(state, "o2", "82-83", "NO_BID", 0.30, 5.0)
        state = negative_risk_apply_fill(state, "o1", 4.0)
        state = negative_risk_reduce_order(state, "o1", 3.0)
        state = negative_risk_apply_fill(state, "o2", 5.0)

        summary = negative_risk_summary(state)
        self.assertEqual(summary["schema_version"], "mm_negative_risk_simulation_v0.1")
        self.assertAlmostEqual(summary["yes_positions"]["80-81"], 4.0)
        self.assertAlmostEqual(summary["no_positions"]["82-83"], 5.0)
        self.assertEqual(summary["open_order_count"], 1)
        self.assertAlmostEqual(summary["open_order_reserves_usdc"], 1.2)
        self.assertAlmostEqual(summary["pusd_collateral_spent_usdc"], 3.1)

        settled = negative_risk_settle(state, "80-81")

        self.assertEqual(len(settled["open_orders"]), 0)
        self.assertAlmostEqual(settled["settlement_redemption_usdc"], 9.0)
        self.assertAlmostEqual(settled["available_balance_usdc"], 105.9)
        self.assertAlmostEqual(settled["ledger"][-1]["realized_pnl_usdc"], 5.9)

    def test_negative_risk_complete_yes_set_conversion_releases_collateral(self):
        state = negative_risk_initial_state(10.0, ["80-81", "82-83"])
        state = negative_risk_place_order(state, "a", "80-81", "YES_BID", 0.40, 2.0)
        state = negative_risk_place_order(state, "b", "82-83", "YES_BID", 0.50, 1.5)
        state = negative_risk_apply_fill(state, "a", 2.0)
        state = negative_risk_apply_fill(state, "b", 1.5)

        converted = negative_risk_convert_complete_sets(state)

        self.assertAlmostEqual(converted["yes_positions"]["80-81"], 0.5)
        self.assertAlmostEqual(converted["yes_positions"]["82-83"], 0.0)
        self.assertAlmostEqual(converted["pusd_collateral_released_usdc"], 1.5)
        self.assertAlmostEqual(converted["available_balance_usdc"], 9.95)
        self.assertEqual(converted["ledger"][-1]["event"], "complete_yes_set_converted")

    def test_negative_risk_rejects_unbacked_orders_and_cancel_all_releases_reserves(self):
        state = negative_risk_initial_state(2.0, ["80-81"])
        rejected = negative_risk_place_order(state, "too-big", "80-81", "YES_BID", 0.75, 4.0)

        self.assertNotIn("too-big", rejected["open_orders"])
        self.assertEqual(rejected["ledger"][-1]["event"], "order_rejected")

        state = negative_risk_place_order(state, "small", "80-81", "YES_BID", 0.50, 2.0)
        self.assertAlmostEqual(state["open_order_reserves_usdc"], 1.0)

        cancelled = negative_risk_cancel_all(state)
        self.assertEqual(cancelled["open_orders"], {})
        self.assertAlmostEqual(cancelled["available_balance_usdc"], 2.0)
        self.assertAlmostEqual(cancelled["open_order_reserves_usdc"], 0.0)


if __name__ == "__main__":
    unittest.main()
