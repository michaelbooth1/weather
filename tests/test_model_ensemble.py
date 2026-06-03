import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.abspath("src"))

from model_ensemble import (  # noqa: E402
    CANDIDATE_PREFIX,
    DEPLOYED_MODEL,
    MARKET_PRICE,
    available_candidates,
    leave_one_day_ensemble,
    load_scored_rows,
)


class TestModelEnsemble(unittest.TestCase):
    def test_market_informed_ensemble_is_separate_and_can_win(self):
        rows = [
            {
                "target_date": "2026-05-27",
                "outcome": 1,
                "bin_type": "eq",
                "bin_value": 20,
                DEPLOYED_MODEL: 0.2,
                MARKET_PRICE: 0.9,
            },
            {
                "target_date": "2026-05-28",
                "outcome": 0,
                "bin_type": "eq",
                "bin_value": 20,
                DEPLOYED_MODEL: 0.8,
                MARKET_PRICE: 0.1,
            },
            {
                "target_date": "2026-05-30",
                "outcome": 1,
                "bin_type": "eq",
                "bin_value": 20,
                DEPLOYED_MODEL: 0.2,
                MARKET_PRICE: 0.9,
            },
        ]

        no_market = leave_one_day_ensemble(rows, available_candidates(rows, include_market=False))
        market = leave_one_day_ensemble(rows, available_candidates(rows, include_market=True))

        self.assertIsNotNone(no_market)
        self.assertIsNotNone(market)
        self.assertLess(market["score"]["brier"], no_market["score"]["brier"])
        self.assertTrue(any(MARKET_PRICE in (cfg["candidate_a"], cfg["candidate_b"]) for cfg in market["configs"]))

    def test_load_scored_rows_joins_component_probabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-toronto-on-may-27-2026"
            folder.mkdir()
            pd.DataFrame([
                {
                    "snapshot_id": "s1",
                    "captured_at_local": "2026-05-27T12:00:00-04:00",
                    "range_label": "20 C",
                    "bin_kind": "eq",
                    "bin_value_c": 20,
                    "model_probability": 0.7,
                    "market_yes": 0.6,
                    "market_no": 0.4,
                    "wu_history_high_c": 20.0,
                },
                {
                    "snapshot_id": "s1",
                    "captured_at_local": "2026-05-27T12:00:00-04:00",
                    "range_label": "21 C",
                    "bin_kind": "eq",
                    "bin_value_c": 21,
                    "model_probability": 0.3,
                    "market_yes": 0.4,
                    "market_no": 0.6,
                    "wu_history_high_c": 20.0,
                },
            ]).to_csv(folder / "snapshots_long.csv", index=False)
            pd.DataFrame([
                {
                    "snapshot_id": "s1",
                    "bin_kind": "eq",
                    "bin_value_c": 20,
                    "component_name": "feature_model",
                    "component_probability": 0.8,
                },
            ]).to_csv(folder / "components_long.csv", index=False)
            (folder / "settlement.json").write_text(
                json.dumps({"quality_grade": "complete"}),
                encoding="utf-8",
            )
            daily = root / "daily.csv"
            daily.write_text("local_date,row_count,max_temp_bucket_c\n", encoding="utf-8")

            rows, metadata = load_scored_rows([folder], daily_summary_path=daily, quality_grades=["complete"])

            self.assertEqual(len(rows), 2)
            self.assertTrue(metadata[0]["included"])
            self.assertEqual(rows[0][f"{CANDIDATE_PREFIX}component_feature_model"], 0.8)


if __name__ == "__main__":
    unittest.main()
