import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.validation.context_guard_validation import (
    DEFAULT_GUARD_KEYS,
    build_context_guard_validation,
    generate_policies,
    read_variant_rows,
    render_report,
)


class TestContextGuardValidation(unittest.TestCase):
    def _write_rows(self, rows):
        path = Path(tempfile.mkdtemp()) / "variant_rows.csv"
        fieldnames = [
            "market_id",
            "target_date",
            "snapshot_id",
            "band_key",
            "probability",
            "current_probability",
            "market_yes",
            "outcome",
            *DEFAULT_GUARD_KEYS,
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def _base_rows(self):
        rows = []
        contexts = [
            ("all_fresh", "cool_side", 0, 0.90, 0.10),
            ("all_fresh", "warm_side", 0, 0.10, 0.90),
            ("stale:open_meteo", "cool_side", 0, 0.10, 0.90),
            ("stale:open_meteo", "warm_side", 1, 0.90, 0.10),
        ]
        for date in ("2026-06-07", "2026-06-08"):
            for index, (source_state, pressure, outcome, probability, current) in enumerate(contexts):
                rows.append({
                    "market_id": "chicago",
                    "target_date": date,
                    "snapshot_id": f"{date}-{index}",
                    "band_key": f"eq:{index}",
                    "probability": probability,
                    "current_probability": current,
                    "market_yes": 0.10 if outcome == 0 else 0.90,
                    "outcome": outcome,
                    "source_freshness_state": source_state,
                    "cutoff_regime": "midday",
                    "forecast_disagreement_bucket": "moderate_disagreement",
                    "forecast_bucket_pressure": pressure,
                    "forecast_source_count_bucket": "two_sources",
                    "bin_type": "eq",
                })
        return rows

    def test_selects_two_condition_current_guard_chronologically(self):
        path = self._write_rows(self._base_rows())

        payload = build_context_guard_validation(
            path,
            max_combo_size=2,
            min_guard_rows=1,
            market_tol=0.003,
        )

        market = payload["market_results"][0]
        self.assertEqual(payload["schema_version"], "context_guard_validation_v0.1")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(
            market["selected_policy"]["policy_id"],
            "current_on_source_freshness_state=all_fresh&forecast_bucket_pressure=cool_side",
        )
        self.assertEqual(market["selected_status"], "PASS")
        self.assertLess(market["selected_eval"]["candidate_brier"], market["baseline_eval"]["candidate_brier"])

    def test_max_combo_size_one_excludes_conjunction_policies(self):
        path = self._write_rows(self._base_rows())
        rows = read_variant_rows(path)

        policies = generate_policies(rows, DEFAULT_GUARD_KEYS, max_combo_size=1, min_guard_rows=1)

        self.assertTrue(policies)
        self.assertFalse(any("&" in policy["policy_id"] for policy in policies))

    def test_render_report_includes_market_selection(self):
        path = self._write_rows(self._base_rows())
        payload = build_context_guard_validation(path, max_combo_size=2, min_guard_rows=1)

        text = render_report(payload)

        self.assertIn("# Current-Blend Context Guard Validation", text)
        self.assertIn("## Market Selection", text)
        self.assertIn("current_on_source_freshness_state=all_fresh", text)


if __name__ == "__main__":
    unittest.main()
