import unittest

from weather.market import mm_exchange as exchange
from weather.market import mm_exchange_reports as reports


class TestMMExchangeReports(unittest.TestCase):
    def test_facade_reexports_report_helpers(self):
        self.assertEqual(exchange.SCHEMA_VERSION, reports.SCHEMA_VERSION)
        self.assertIs(exchange.build_pilot_report_payload, reports.build_pilot_report_payload)
        self.assertIs(exchange.render_pilot_report, reports.render_pilot_report)
        self.assertIs(exchange.build_reconciliation_report, reports.build_reconciliation_report)
        self.assertIs(exchange.maker_rebate_reconciliation, reports.maker_rebate_reconciliation)

    def test_pilot_report_payload_and_markdown_are_owned_by_report_module(self):
        reconciliation = {
            "generated_at_utc": "2026-06-14T16:00:00+00:00",
            "run_id": "exchange-run",
            "target_date": "2026-06-14",
            "status": "PASS",
            "matched_order_count": 2,
            "user_stream_lifecycle_events": [{"transition": "canceled"}],
            "balances": {
                "starting_cash_usdc": "25.00",
                "ending_cash_usdc": "26.00",
            },
            "rewards": {
                "maker_rebate_evidence": {
                    "status": "OBSERVED",
                    "query_scope": "exact_maker_date",
                    "http_status": 200,
                    "response_sha256": "e" * 64,
                    "request_url": (
                        "https://clob.polymarket.com/rebates/current?"
                        "date=2026-06-14&maker_address=0x" + "a" * 40
                    ),
                    "query_date": "2026-06-14",
                    "queried_at_utc": "2026-06-15T01:00:00+00:00",
                    "maker_address": "0x" + "a" * 40,
                    "condition_id": "0x" + "b" * 64,
                    "payout_cycle_complete": True,
                    "rows": [{
                        "date": "2026-06-14",
                        "maker_address": "0x" + "a" * 40,
                        "condition_id": "0x" + "b" * 64,
                        "asset_address": "0x" + "c" * 40,
                        "rebated_fees_usdc": "0.01",
                    }],
                },
            },
            "fees": {
                "actual_fee_evidence": {
                    "status": "OBSERVED",
                    "coverage": "all_pilot_trades_and_exits",
                    "includes_taker_and_flattening_fees": True,
                    "calculation_basis": "confirmed_trade_events",
                    "fee_formula": "shares_x_rate_x_price_x_one_minus_price",
                    "maker_fees_zero": True,
                    "precision_decimal_places": 5,
                    "confirmed_trade_set_sha256": "f" * 64,
                    "maker_address": "0x" + "a" * 40,
                    "condition_id": "0x" + "b" * 64,
                    "observed_fill_count": 1,
                    "paid_usdc": "0.00",
                },
            },
            "positions": [],
            "position_evidence": {
                "status": "OBSERVED",
                "query_scope": "exact_maker_condition",
                "maker_address": "0x" + "a" * 40,
                "condition_id": "0x" + "b" * 64,
                "rows": [],
                "http_status": 200,
                "response_sha256": "f" * 64,
                "request_url": (
                    "https://data-api.polymarket.com/positions?user=0x"
                    + "a" * 40
                    + "&market=0x"
                    + "b" * 64
                    + "&sizeThreshold=0&limit=500&offset=0"
                ),
            },
            "financial_identity": {
                "external_cash_flows_usdc": 0.0,
                "ending_positions_zero": True,
                "settlement_pnl_excludes_fees_and_incentives": True,
            },
            "redemption_status": {
                "redemption_usdc": "1.00",
                "settlement_pnl_usdc": "0.99",
            },
        }
        quote_rows = [{
            "quote_permission": "True",
            "expected_rebate_value": "0.01",
            "expected_reward_score": "0.25",
        }]
        fill_rows = [{
            "fill_price": "0.49",
            "fill_size": "2",
            "exchange_order_id": "order-1",
            "trade_id": "trade-1",
            "transaction_hash": "0x" + "d" * 64,
            "maker_address": "0x" + "a" * 40,
            "condition_id": "0x" + "b" * 64,
            "clob_token_id": "token-1",
            "liquidity_role": "MAKER",
            "fee_rate_bps": "500",
            "official_trade_status": "CONFIRMED",
            "markout_30m": "0.02",
            "maker_rebate_estimate_usdc": "0.01",
        }]
        reconciliation["fees"]["actual_fee_evidence"][
            "confirmed_trade_set_sha256"
        ] = reports.confirmed_trade_set_sha256(fill_rows)
        probe_status = reports.mm2_probe_status(
            reconciliation,
            probe_evidence={
                "heartbeat_dead_man": {"passed": True, "detail": "heartbeat probe observed"},
                "min_size_tick_post_only": True,
            },
        )

        payload = reports.build_pilot_report_payload(
            reconciliation,
            quote_rows,
            fill_rows,
            probe_status,
        )
        markdown = reports.render_pilot_report(payload)
        reconciliation_markdown = reports.build_reconciliation_report({
            **reconciliation,
            "trading_verbs_enabled": False,
            "item45_gates": {"ok": True},
            "credential_diagnostics": {"values_redacted": True},
            "adapter_request_diagnostics": {
                "capability_matrix": {"supported_actions": ["open_orders"]},
                "ready_plan_count": 1,
                "blocked_plan_count": 0,
            },
            "local_live_order_count": 2,
            "exchange_open_order_count": 2,
            "missing_exchange_order_count": 0,
            "extra_exchange_order_count": 0,
            "user_stream_event_count": 1,
            "mm2_probe_status": probe_status,
        })

        self.assertTrue(payload["evidence_complete"])
        self.assertTrue(payload["financial_reconciliation_complete"])
        self.assertAlmostEqual(payload["live_notional_usdc"], 0.98)
        self.assertTrue(payload["maker_rebate_reconciled"])
        self.assertAlmostEqual(
            payload["financial_reconciliation"]["actual_total_pnl_after_fees_incentives_usdc"],
            1.0,
        )
        self.assertIn("# MM-2 Pilot Report", markdown)
        self.assertIn("heartbeat_dead_man", reconciliation_markdown)

    def test_cancel_all_probe_requires_zero_open_order_confirmation(self):
        pending = reports.mm2_probe_status(
            {
                "matched_order_count": 2,
                "user_stream_lifecycle_events": [{"transition": "canceled"}],
            },
            probe_evidence={
                "cancel_all_verification": {
                    "passed": True,
                    "cancel_all_sent": True,
                    "cancel_all_response": {"canceledOrderIds": ["ex-1"]},
                },
            },
        )
        observed = reports.mm2_probe_status(
            {
                "matched_order_count": 2,
                "user_stream_lifecycle_events": [{"transition": "canceled"}],
            },
            probe_evidence={
                "cancel_all_verification": {
                    "passed": True,
                    "cancel_all_sent": True,
                    "cancel_all_response": {"canceledOrderIds": ["ex-1"]},
                    "open_orders_after_cancel_all": [],
                },
            },
        )

        self.assertEqual(
            pending["cancel_all_verification"]["status"],
            "pending_zero_open_order_confirmation",
        )
        self.assertEqual(observed["cancel_all_verification"]["status"], "observed")

    def test_reward_campaign_metadata_does_not_count_as_rebate_payout_evidence(self):
        status = reports.mm2_probe_status(
            {
                "rewards": {"current_markets": [{"condition_id": "condition-1"}]},
                "user_stream_lifecycle_events": [],
            },
        )

        self.assertEqual(
            status["reward_rebate_reconciliation"]["status"],
            "pending_next_cycle",
        )

    def test_completed_empty_rebate_cycle_is_reconciled_zero(self):
        reconciliation = reports.maker_rebate_reconciliation({
            "maker_rebate_evidence": {
                "status": "OBSERVED",
                "query_scope": "exact_maker_date",
                "http_status": 200,
                "response_sha256": "e" * 64,
                "request_url": (
                    "https://clob.polymarket.com/rebates/current?"
                    "date=2026-06-14&maker_address=0x" + "a" * 40
                ),
                "query_date": "2026-06-14",
                "queried_at_utc": "2026-06-15T01:00:00+00:00",
                "maker_address": "0x" + "a" * 40,
                "condition_id": "0x" + "b" * 64,
                "payout_cycle_complete": True,
                "rows": [],
            },
        })

        self.assertTrue(reconciliation["complete"])
        self.assertEqual(reconciliation["actual_maker_rebate_usdc"], 0.0)

    def test_empty_positions_and_configured_fee_rate_are_not_actual_financial_evidence(self):
        financial = reports.build_financial_reconciliation(
            {
                "balances": {
                    "starting_cash_usdc": "25.00",
                    "ending_cash_usdc": "25.00",
                },
                "positions": [],
                "fees": {"fee_rate_bps": "50"},
                "rewards": {},
                "redemption_status": {},
            },
            [],
            [],
        )

        self.assertFalse(financial["complete"])
        self.assertFalse(financial["ending_positions_zero_observed"])
        self.assertIsNone(financial["actual_fees_usdc"])
        self.assertIn("position_reconciliation", financial["missing_evidence"])
        self.assertIn("actual_fees", financial["missing_evidence"])

    def test_actual_fee_reconciliation_hashes_fills_and_charges_only_takers(self):
        maker = "0x" + "a" * 40
        condition = "0x" + "b" * 64
        fills = [
            {
                "trade_id": "maker-trade",
                "transaction_hash": "0x" + "c" * 64,
                "lifecycle_key": "maker-order",
                "exchange_order_id": "maker-order",
                "maker_address": maker,
                "condition_id": condition,
                "clob_token_id": "token-1",
                "liquidity_role": "MAKER",
                "side": "BUY",
                "fill_price": "0.50",
                "fill_size": "2",
                "fee_rate_bps": "500",
                "official_trade_status": "CONFIRMED",
            },
            {
                "trade_id": "taker-trade",
                "transaction_hash": "0x" + "d" * 64,
                "lifecycle_key": "taker-order",
                "exchange_order_id": "taker-order",
                "maker_address": maker,
                "condition_id": condition,
                "clob_token_id": "token-1",
                "liquidity_role": "TAKER",
                "side": "SELL",
                "fill_price": "0.50",
                "fill_size": "2",
                "fee_rate_bps": "500",
                "official_trade_status": "CONFIRMED",
            },
        ]
        evidence = {
            "actual_fee_evidence": {
                "status": "OBSERVED",
                "coverage": "all_pilot_trades_and_exits",
                "includes_taker_and_flattening_fees": True,
                "calculation_basis": "confirmed_trade_events",
                "fee_formula": "shares_x_rate_x_price_x_one_minus_price",
                "maker_fees_zero": True,
                "precision_decimal_places": 5,
                "confirmed_trade_set_sha256": reports.confirmed_trade_set_sha256(fills),
                "maker_address": maker,
                "condition_id": condition,
                "observed_fill_count": 2,
                "paid_usdc": "0.02500",
            },
        }

        result = reports.actual_fee_reconciliation(evidence, fills)

        self.assertTrue(result["complete"], result["blockers"])
        self.assertEqual(result["actual_fees_usdc"], 0.025)
        self.assertEqual(result["calculated_fees_usdc"], 0.025)

        fills[1]["fill_price"] = "0.40"
        tampered = reports.actual_fee_reconciliation(evidence, fills)
        self.assertFalse(tampered["complete"])
        self.assertIn("actual_fee_trade_evidence_hash_mismatch", tampered["blockers"])
        self.assertIn("actual_fee_amount_mismatch", tampered["blockers"])

    def test_rebate_reconciliation_rejects_noncanonical_scope(self):
        reconciliation = reports.maker_rebate_reconciliation({
            "maker_rebate_evidence": {
                "status": "OBSERVED",
                "query_date": "June 14",
                "maker_address": "maker",
                "condition_id": "condition",
                "payout_cycle_complete": True,
                "rows": [],
            },
        })

        self.assertFalse(reconciliation["complete"])
        self.assertIn("maker_rebate_scope_incomplete", reconciliation["blockers"])

    def test_reconciliation_rejects_query_urls_with_wrong_exact_scope(self):
        maker = "0x" + "a" * 40
        condition = "0x" + "b" * 64
        wrong_maker = "0x" + "c" * 40
        rebate = reports.maker_rebate_reconciliation({
            "maker_rebate_evidence": {
                "status": "OBSERVED",
                "query_scope": "exact_maker_date",
                "query_date": "2026-08-13",
                "queried_at_utc": "2026-08-14T01:00:00+00:00",
                "maker_address": maker,
                "condition_id": condition,
                "request_url": (
                    "https://clob.polymarket.com/rebates/current?"
                    f"date=2026-08-13&maker_address={wrong_maker}"
                ),
                "http_status": 200,
                "response_sha256": "d" * 64,
                "payout_cycle_complete": True,
                "rows": [],
            }
        })
        positions = reports.position_reconciliation({
            "positions": [],
            "position_evidence": {
                "status": "OBSERVED",
                "query_scope": "exact_maker_condition",
                "maker_address": maker,
                "condition_id": condition,
                "request_url": (
                    "https://data-api.polymarket.com/positions?"
                    f"user={maker}&market={'0x' + 'c' * 64}&sizeThreshold=0"
                    "&limit=500&offset=0"
                ),
                "http_status": 200,
                "response_sha256": "e" * 64,
                "rows": [],
            },
        })

        self.assertIn("maker_rebate_request_url_invalid", rebate["blockers"])
        self.assertIn("position_request_url_invalid", positions["blockers"])


if __name__ == "__main__":
    unittest.main()
