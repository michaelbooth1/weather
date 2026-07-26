import os
import sys
import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import weather.reporting.location_analysis.location_trust as location_trust
from weather.reporting.location_analysis.location_trust import grade_for, score_market, trust_from_components


SLUG = "highest-temperature-in-toronto-on-july-1-2026"


def write_tape(root):
    folder = Path(root) / SLUG
    folder.mkdir(parents=True)
    columns = [
        "snapshot_id",
        "captured_at_local",
        "event_slug",
        "range_label",
        "bin_kind",
        "bin_value_c",
        "model_probability",
        "market_yes",
        "market_no",
        "wu_history_high_c",
    ]
    rows = [
        {
            "snapshot_id": "s1",
            "captured_at_local": "2026-07-01T10:00:00-04:00",
            "event_slug": SLUG,
            "range_label": "25 C",
            "bin_kind": "eq",
            "bin_value_c": "25",
            "model_probability": "0.40",
            "market_yes": "0.60",
            "market_no": "0.40",
            "wu_history_high_c": "25.0",
        },
        {
            "snapshot_id": "s1",
            "captured_at_local": "2026-07-01T10:00:00-04:00",
            "event_slug": SLUG,
            "range_label": "26 C",
            "bin_kind": "eq",
            "bin_value_c": "26",
            "model_probability": "0.20",
            "market_yes": "0.30",
            "market_no": "0.70",
            "wu_history_high_c": "25.0",
        },
        {
            "snapshot_id": "s2",
            "captured_at_local": "2026-07-01T11:00:00-04:00",
            "event_slug": SLUG,
            "range_label": "25 C",
            "bin_kind": "eq",
            "bin_value_c": "25",
            "model_probability": "0.70",
            "market_yes": "0.50",
            "market_no": "0.50",
            "wu_history_high_c": "25.0",
        },
        {
            "snapshot_id": "s2",
            "captured_at_local": "2026-07-01T11:00:00-04:00",
            "event_slug": SLUG,
            "range_label": "26 C",
            "bin_kind": "eq",
            "bin_value_c": "26",
            "model_probability": "0.10",
            "market_yes": "0.20",
            "market_no": "0.80",
            "wu_history_high_c": "25.0",
        },
    ]
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    (folder / "settlement.json").write_text(
        json.dumps(
            {
                "event_slug": SLUG,
                "market_id": "toronto",
                "target_date": "2026-07-01",
                "settlement_bucket": 25,
                "settlement_unit": "C",
                "quality_grade": "complete",
                "settlement_source": "test",
            }
        ),
        encoding="utf-8",
    )


class TestTrustFormula(unittest.TestCase):
    def test_unproven_when_no_settled_days(self):
        r = trust_from_components(0, None)
        self.assertEqual(r["grade"], "Unproven")
        self.assertLessEqual(r["trust_score"], 20)
        self.assertIsNone(r["calibration_subscore"])

    def test_mature_well_calibrated_scores_high(self):
        r = trust_from_components(40, 0.03)
        self.assertGreaterEqual(r["trust_score"], 80)
        self.assertEqual(r["grade"], "Strong")

    def test_poor_calibration_capped_even_with_data(self):
        # Lots of days but ECE at the poor floor -> calibration gates it low.
        r = trust_from_components(40, 0.16)
        self.assertLessEqual(r["trust_score"], 20)

    def test_more_days_raises_score(self):
        low = trust_from_components(5, 0.08)["trust_score"]
        high = trust_from_components(25, 0.08)["trust_score"]
        self.assertGreater(high, low)

    def test_better_calibration_raises_score(self):
        worse = trust_from_components(20, 0.11)["trust_score"]
        better = trust_from_components(20, 0.05)["trust_score"]
        self.assertGreater(better, worse)

    def test_grade_bands(self):
        self.assertEqual(grade_for(85), "Strong")
        self.assertEqual(grade_for(70), "Good")
        self.assertEqual(grade_for(50), "Moderate")
        self.assertEqual(grade_for(30), "Low")
        self.assertEqual(grade_for(10), "Unproven")

    def test_score_market_reports_winner_band_catchup(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_tape(tmp)
            # Isolate from the real settlement ledger: once the real market
            # settles this fixture's slug/date, settlement_for_tape's
            # slug-based ledger lookup would override the fixture settlement.
            original_ledger_root = os.environ.get("SETTLEMENT_LEDGER_ROOT")
            os.environ["SETTLEMENT_LEDGER_ROOT"] = str(Path(tmp) / "settlements")
            try:
                row = score_market(
                    "toronto",
                    root=tmp,
                    daily_summary=Path(tmp) / "missing_daily.csv",
                    as_of=date(2026, 7, 2),
                )
            finally:
                if original_ledger_root is None:
                    os.environ.pop("SETTLEMENT_LEDGER_ROOT", None)
                else:
                    os.environ["SETTLEMENT_LEDGER_ROOT"] = original_ledger_root

            self.assertEqual(row["settled_days"], 1)
            self.assertEqual(row["winner_rows"], 2)
            self.assertAlmostEqual(row["winner_model_probability"], 0.55)
            self.assertAlmostEqual(row["winner_market_probability"], 0.55)
            self.assertAlmostEqual(row["winner_catchup_gap"], 0.0)
            self.assertAlmostEqual(row["winner_catchup_rate"], 0.5)

    def test_trust_target_date_whitelist_is_exact_and_default_is_unchanged(self):
        first = Path(
            "highest-temperature-in-toronto-on-july-1-2026"
        )
        second = Path(
            "highest-temperature-in-toronto-on-july-2-2026"
        )
        label = {
            "settlement_bucket": 25,
            "quality_grade": "complete",
        }
        with (
            patch.object(
                location_trust,
                "discover_settled_folders",
                return_value=[first, second],
            ),
            patch.object(
                location_trust,
                "spec_for_slug",
                return_value=SimpleNamespace(id="toronto"),
            ),
            patch.object(
                location_trust,
                "load_market_day_label",
                return_value=label,
            ),
        ):
            ambient = location_trust.market_settled_folders(
                "toronto",
                Path("snapshots"),
                date(2026, 7, 3),
            )
            selected = location_trust.market_settled_folders(
                "toronto",
                Path("snapshots"),
                date(2026, 7, 3),
                included_target_dates={"2026-07-01"},
            )
            empty = location_trust.market_settled_folders(
                "toronto",
                Path("snapshots"),
                date(2026, 7, 3),
                included_target_dates=set(),
            )

        self.assertEqual(ambient, [first, second])
        self.assertEqual(selected, [first])
        self.assertEqual(empty, [])

    def test_score_all_materializes_target_date_whitelist_once(self):
        specs = [SimpleNamespace(id="toronto"), SimpleNamespace(id="denver")]
        dates = (value for value in ["2026-07-01", "2026-07-02"])
        with (
            patch.object(location_trust, "all_specs", return_value=specs),
            patch.object(
                location_trust,
                "score_market",
                side_effect=lambda market_id, *_args, **_kwargs: {
                    "market": market_id
                },
            ) as score,
        ):
            rows = location_trust.score_all_markets(
                root=Path("snapshots"),
                included_target_dates=dates,
            )

        self.assertEqual(rows, [{"market": "toronto"}, {"market": "denver"}])
        expected = frozenset({"2026-07-01", "2026-07-02"})
        self.assertEqual(len(score.call_args_list), 2)
        for call_row in score.call_args_list:
            self.assertEqual(
                call_row.kwargs["included_target_dates"],
                expected,
            )


if __name__ == "__main__":
    unittest.main()
