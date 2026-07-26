import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import weather.reporting.location_analysis.location_trust as location_trust
import weather.reporting.promotion.promotion_gauntlet as promotion_gauntlet


class TestPromotionGauntletFrozenTrust(unittest.TestCase):
    def test_frozen_trust_ignores_unrelated_bad_ledger_and_live_folders(self):
        rows = [
            {
                "market_id": "toronto",
                "target_date": "2026-07-01",
                "recorded_p": 0.75,
                "market_yes": 0.55,
                "outcome": 1,
            },
            {
                "market_id": "toronto",
                "target_date": "2026-07-01",
                "recorded_p": 0.25,
                "market_yes": 0.45,
                "outcome": 0,
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad_folder = (
                root
                / "snapshots"
                / "highest-temperature-in-toronto-on-july-3-2025"
            )
            bad_folder.mkdir(parents=True)
            (bad_folder / "snapshots_long.csv").write_text(
                "recorded_p,market_yes,outcome\n",
                encoding="utf-8",
            )
            (bad_folder / "settlement.json").write_text(
                "{not valid json",
                encoding="utf-8",
            )
            bad_ledger = root / "settlement-ledger" / "toronto"
            bad_ledger.mkdir(parents=True)
            (bad_ledger / "ledger.jsonl").write_text(
                "{also not valid json",
                encoding="utf-8",
            )
            with (
                patch.dict(
                    os.environ,
                    {"SETTLEMENT_LEDGER_ROOT": str(bad_ledger.parent)},
                ),
                patch.object(
                    location_trust,
                    "discover_settled_folders",
                    side_effect=AssertionError("live discovery is forbidden"),
                ) as discover,
                patch.object(
                    promotion_gauntlet,
                    "score_replay_rows",
                    wraps=location_trust.score_replay_rows,
                ) as score,
            ):
                trust = promotion_gauntlet._frozen_trust_by_market(rows)

        discover.assert_not_called()
        score.assert_called_once_with(rows)
        self.assertFalse(hasattr(promotion_gauntlet, "score_all_markets"))
        self.assertEqual(trust["toronto"]["settled_days"], 1)
        self.assertEqual(trust["toronto"]["band_rows"], 2)


if __name__ == "__main__":
    unittest.main()
