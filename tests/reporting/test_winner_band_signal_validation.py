import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.validation.winner_band_signal_validation import (
    build_payload,
    enrich_rows,
    nested_market_date_split,
    normalize_snapshot_weights,
    write_markdown_report,
)


FIELDS = [
    "market_id",
    "target_date",
    "snapshot_id",
    "band_key",
    "probability",
    "current_probability",
    "recorded_probability",
    "market_yes",
    "outcome",
    "bin_type",
    "cutoff_hour",
    "cutoff_regime",
    "forecast_bucket_pressure",
    "forecast_disagreement_bucket",
    "forecast_source_count_bucket",
    "source_freshness_state",
]


def row(day, snapshot, band, probability, current, market, outcome, bin_type="eq", **extra):
    data = {
        "market_id": extra.get("market_id", "nyc"),
        "target_date": day,
        "snapshot_id": snapshot,
        "band_key": band,
        "probability": probability,
        "current_probability": current,
        "recorded_probability": extra.get("recorded_probability", probability),
        "market_yes": market,
        "outcome": outcome,
        "bin_type": bin_type,
        "cutoff_hour": extra.get("cutoff_hour", 8),
        "cutoff_regime": extra.get("cutoff_regime", "early"),
        "forecast_bucket_pressure": extra.get("forecast_bucket_pressure", "near_forecast"),
        "forecast_disagreement_bucket": extra.get("forecast_disagreement_bucket", "low"),
        "forecast_source_count_bucket": extra.get("forecast_source_count_bucket", "many"),
        "source_freshness_state": extra.get("source_freshness_state", "all_fresh"),
    }
    return {key: str(value) for key, value in data.items()}


def write_rows(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def day_rows(day, snapshot, winner="eq:80"):
    bands = ["eq:78", "eq:80", "eq:82", "gte:84"]
    rows = []
    for band in bands:
        outcome = 1 if band == winner else 0
        rows.append(row(
            day,
            snapshot,
            band,
            0.55 if band == "eq:80" else 0.20 if band == "eq:82" else 0.15 if band == "eq:78" else 0.10,
            0.50 if band == "eq:80" else 0.20 if band == "eq:82" else 0.20 if band == "eq:78" else 0.10,
            0.65 if band == winner else 0.12,
            outcome,
            bin_type="gte" if band.startswith("gte") else "eq",
        ))
    return rows


class WinnerBandSignalValidationTests(unittest.TestCase):
    def test_enrich_rows_adds_inference_time_rank_features(self):
        rows = [
            {
                "market_id": "nyc",
                "target_date": "2026-06-01",
                "snapshot_id": "s1",
                "band_key": "eq:80",
                "probability": 0.70,
                "current_probability": 0.20,
                "recorded_probability": 0.60,
            },
            {
                "market_id": "nyc",
                "target_date": "2026-06-01",
                "snapshot_id": "s1",
                "band_key": "eq:82",
                "probability": 0.30,
                "current_probability": 0.80,
                "recorded_probability": 0.40,
            },
        ]

        enriched = enrich_rows(rows)

        self.assertEqual(enriched[0]["candidate_rank"], 1)
        self.assertEqual(enriched[1]["current_rank"], 1)
        self.assertEqual(enriched[0]["candidate_rank_bucket"], "top1")
        self.assertAlmostEqual(enriched[0]["band_value"], 80.0)
        self.assertIn("logit_probability", enriched[0])

    def test_normalize_snapshot_weights_keeps_snapshot_mass_at_one(self):
        rows = [
            {"market_id": "nyc", "target_date": "2026-06-01", "snapshot_id": "s1"},
            {"market_id": "nyc", "target_date": "2026-06-01", "snapshot_id": "s1"},
        ]

        probabilities = normalize_snapshot_weights(rows, [2.0, 3.0])

        self.assertAlmostEqual(sum(probabilities), 1.0)
        self.assertAlmostEqual(probabilities[1], 0.60)

    def test_nested_market_date_split_uses_selection_date_before_eval(self):
        rows = [
            {"market_id": "nyc", "target_date": "2026-06-01"},
            {"market_id": "nyc", "target_date": "2026-06-02"},
            {"market_id": "nyc", "target_date": "2026-06-03"},
            {"market_id": "nyc", "target_date": "2026-06-04"},
        ]

        split = nested_market_date_split(rows)["nyc"]

        self.assertEqual(split["fit_dates"], ["2026-06-01"])
        self.assertEqual(split["selection_dates"], ["2026-06-02"])
        self.assertEqual(split["eval_dates"], ["2026-06-03", "2026-06-04"])

    def test_build_payload_reports_nested_holdout_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows_path = Path(tmp) / "rows.csv"
            report_path = Path(tmp) / "report.md"
            write_rows(rows_path, [
                *day_rows("2026-06-01", "s1", winner="eq:80"),
                *day_rows("2026-06-02", "s2", winner="eq:80"),
                *day_rows("2026-06-03", "s3", winner="eq:82"),
                *day_rows("2026-06-04", "s4", winner="eq:82"),
            ])

            payload = build_payload([rows_path])
            write_markdown_report(report_path, payload)
            report_text = report_path.read_text(encoding="utf-8")

        self.assertEqual(payload["schema_version"], "winner_band_signal_validation_v0.1")
        self.assertEqual(payload["split_by_market"]["nyc"]["fit_dates"], ["2026-06-01"])
        self.assertEqual(payload["split_by_market"]["nyc"]["selection_dates"], ["2026-06-02"])
        self.assertEqual(payload["split_by_market"]["nyc"]["eval_dates"], ["2026-06-03", "2026-06-04"])
        self.assertIn(payload["selected_transform"], {"baseline", "current", "row_norm", "row_mult", "row_sqrt", "row_raw25"})
        self.assertEqual(payload["no_leakage_audit"]["status"], "PASS")
        self.assertIn("Selection Holdout", report_text)
        self.assertIn("not promotion evidence", report_text)


if __name__ == "__main__":
    unittest.main()
