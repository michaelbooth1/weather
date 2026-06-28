import unittest

from weather.market.taker_evidence_starvation import classify_taker_evidence_starvation


def _clob_discovery_summary(reason_counts):
    # A latest tick that scored rows, took no fills, and whose upstream check
    # mapped the first failing dependency to "clob" via the market-availability
    # `clob_discovery` gate (not loop-death / stale-book).
    return {
        "upstream_dependency_status": {
            "status": "BLOCK",
            "first_failing_dependency": "clob",
            "first_failing_gate": "clob_discovery",
        },
        "latest_tick_rows": 132,
        "latest_tick_filled_orders": 0,
        "cumulative_filled_orders": 0,
        "root_cause_class": "blocked_by_market_discovery",
        "first_failing_gate": "clob_discovery",
        "reason_counts": reason_counts,
    }


class TestClobDiscoveryNotInfraStarvation(unittest.TestCase):
    def test_no_ask_liquidity_is_risk_clean_not_infra_starved(self):
        # Book was read but has no ask-side liquidity / out-of-range prices --
        # RISK_CLEAN reasons. The CLOB collection loop is healthy; this must NOT
        # be classified as infra_starved_clob, and must be countable.
        result = classify_taker_evidence_starvation(
            summary=_clob_discovery_summary({
                "NO_TRADE_NO_ASK_SIZE": 106,
                "NO_TRADE_PRICE_OUT_OF_RANGE": 26,
            })
        )
        self.assertEqual(result["classification"], "risk_clean_no_edge")
        self.assertNotEqual(result["status"], "BLOCK")

    def test_stale_book_evidence_still_infra_starved_clob(self):
        # Genuine CLOB infra: stale/missing book reasons present -> stays
        # infra_starved_clob and blocking (countability preserved).
        result = classify_taker_evidence_starvation(
            summary=_clob_discovery_summary({
                "NO_TRADE_STALE_BOOK": 16,
                "NO_TRADE_NO_ASK_SIZE": 4,
            })
        )
        self.assertEqual(result["classification"], "infra_starved_clob")
        self.assertEqual(result["status"], "BLOCK")

    def test_clob_dependency_with_no_reasons_stays_infra_starved(self):
        # Dead/blocked CLOB with no scored reasons (e.g. loop dead, taker could
        # not evaluate books) -> the clean guard does not apply (no risk-clean
        # reasons), so it stays infra_starved_clob.
        summary = _clob_discovery_summary({})
        summary["first_failing_gate"] = "clob_loop"
        result = classify_taker_evidence_starvation(summary=summary)
        self.assertEqual(result["classification"], "infra_starved_clob")
        self.assertEqual(result["status"], "BLOCK")

    def test_snapshot_dependency_clean_reasons_is_not_infra_starved(self):
        # Symmetric guard for the snapshot dependency.
        result = classify_taker_evidence_starvation(
            summary={
                "upstream_dependency_status": {
                    "status": "BLOCK",
                    "first_failing_dependency": "snapshot",
                    "first_failing_gate": "snapshot_model_rows",
                },
                "latest_tick_rows": 50,
                "latest_tick_filled_orders": 0,
                "cumulative_filled_orders": 0,
                "reason_counts": {"NO_TRADE_EDGE_TOO_SMALL": 50},
            }
        )
        self.assertEqual(result["classification"], "risk_clean_no_edge")
        self.assertNotEqual(result["status"], "BLOCK")


if __name__ == "__main__":
    unittest.main()
