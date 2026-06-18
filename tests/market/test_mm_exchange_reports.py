import unittest

from weather.market import mm_exchange as exchange
from weather.market import mm_exchange_reports as reports


class TestMMExchangeReports(unittest.TestCase):
    def test_facade_reexports_report_helpers(self):
        self.assertEqual(exchange.SCHEMA_VERSION, reports.SCHEMA_VERSION)
        self.assertIs(exchange.build_pilot_report_payload, reports.build_pilot_report_payload)
        self.assertIs(exchange.render_pilot_report, reports.render_pilot_report)
        self.assertIs(exchange.build_reconciliation_report, reports.build_reconciliation_report)

    def test_pilot_report_payload_and_markdown_are_owned_by_report_module(self):
        reconciliation = {
            "generated_at_utc": "2026-06-14T16:00:00+00:00",
            "run_id": "exchange-run",
            "target_date": "2026-06-14",
            "status": "PASS",
            "matched_order_count": 2,
            "user_stream_lifecycle_events": [{"transition": "canceled"}],
            "balances": {"starting_cash_usdc": "25.00", "cash": "25.98"},
            "rewards": {"maker_rebate_usdc": "0.01"},
            "fees": {"paid_usdc": "0.02"},
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
            "markout_30m": "0.02",
        }]
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
        self.assertAlmostEqual(
            payload["financial_reconciliation"]["actual_total_pnl_after_fees_incentives_usdc"],
            0.98,
        )
        self.assertIn("# MM-2 Pilot Report", markdown)
        self.assertIn("heartbeat_dead_man", reconciliation_markdown)


if __name__ == "__main__":
    unittest.main()
