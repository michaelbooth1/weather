import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.model_scoring_liveness import (
    build_scoring_liveness,
    latest_settled_label_summary,
)


def _write_labels(path):
    rows = [
        {
            "event_slug": "highest-temperature-in-toronto-on-june-21-2026",
            "market_id": "toronto",
            "target_date": "2026-06-21",
            "quality_grade": "complete",
            "settlement_bucket": "25",
        },
        {
            "event_slug": "highest-temperature-in-nyc-on-june-23-2026",
            "market_id": "nyc",
            "target_date": "2026-06-23",
            "quality_grade": "manual_override",
            "settlement_bucket": "82",
        },
        {
            "event_slug": "highest-temperature-in-miami-on-june-24-2026",
            "market_id": "miami",
            "target_date": "2026-06-24",
            "quality_grade": "partial",
            "settlement_bucket": "90",
        },
    ]
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class ModelScoringLivenessTests(unittest.TestCase):
    def test_latest_settled_label_uses_promotion_countable_quality_grades(self):
        with tempfile.TemporaryDirectory() as tmp:
            labels = Path(tmp) / "labels.csv"
            _write_labels(labels)

            summary = latest_settled_label_summary(labels, quality_grades=("complete", "manual_override"))
            stale = build_scoring_liveness(
                artifact_name="hourly_model_performance",
                labels_csv=labels,
                quality_grades=("complete", "manual_override"),
                last_scored_target_date="2026-06-21",
                rerun_command="python -m weather.reporting.hourly_model_performance",
            )
            fresh = build_scoring_liveness(
                artifact_name="hourly_model_performance",
                labels_csv=labels,
                quality_grades=("complete", "manual_override"),
                last_scored_target_date="2026-06-23",
            )

        self.assertEqual(summary["latest_settled_label_date"], "2026-06-23")
        self.assertEqual(summary["selected_label_count"], 2)
        self.assertEqual(stale["status"], "BLOCK")
        self.assertIn("older than latest settled label 2026-06-23", stale["first_blocker"]["detail"])
        self.assertEqual(fresh["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
