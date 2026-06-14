import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from forecast_tracker import (
    day_record,
    forecasts_from_rows,
    median_bucket,
    reach_probability,
    run,
    source_calibration,
)

COLUMNS = [
    "snapshot_id", "captured_at_local", "range_label", "bin_kind", "bin_value_c",
    "model_probability", "market_yes",
    "eccc_forecast_high_c", "weather_forecast_max_c", "open_meteo_max_c", "wu_history_high_c",
]


def write_day(root, slug, snapshots, settle):
    """snapshots: list of (captured_local, forecasts dict, bands list of (kind,value,model,market))."""
    folder = Path(root) / slug
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for captured, forecasts, bands in snapshots:
        sid = captured.replace(":", "").replace("-", "")
        for kind, value, model_p, market_p in bands:
            rows.append({
                "snapshot_id": sid,
                "captured_at_local": captured,
                "range_label": f"{value} {kind}",
                "bin_kind": kind,
                "bin_value_c": value,
                "model_probability": model_p,
                "market_yes": market_p,
                "eccc_forecast_high_c": forecasts.get("eccc", ""),
                "weather_forecast_max_c": forecasts.get("weather_com", ""),
                "open_meteo_max_c": forecasts.get("open_meteo", ""),
                "wu_history_high_c": settle,
            })
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return folder


# bands: lte_24, eq_25..28, gte_29
def bands(model_gte29, market_gte29, mid=0.10):
    eq = [("eq", v, mid, mid) for v in (25, 26, 27, 28)]
    # make the side probabilities sum to ~1
    lte_m = max(0.0, 1.0 - model_gte29 - 4 * mid)
    lte_k = max(0.0, 1.0 - market_gte29 - 4 * mid)
    return [("lte", 24, lte_m, lte_k)] + eq + [("gte", 29, model_gte29, market_gte29)]


class TestPureHelpers(unittest.TestCase):
    def test_reach_probability_at_gte_boundary(self):
        b = [{"bin_kind": "lte", "bin_value_c": 24, "model_probability": 0.5},
             {"bin_kind": "eq", "bin_value_c": 27, "model_probability": 0.3},
             {"bin_kind": "gte", "bin_value_c": 29, "model_probability": 0.2}]
        self.assertAlmostEqual(reach_probability(b, 29, "model_probability"), 0.2)  # gte tail only
        self.assertAlmostEqual(reach_probability(b, 27, "model_probability"), 0.5)  # eq27 + gte29
        self.assertIsNone(reach_probability(b, 24, "model_probability"))            # can't split low tail

    def test_median_bucket(self):
        b = [{"bin_kind": "lte", "bin_value_c": 24, "model_probability": 0.1},
             {"bin_kind": "eq", "bin_value_c": 25, "model_probability": 0.1},
             {"bin_kind": "eq", "bin_value_c": 26, "model_probability": 0.5},
             {"bin_kind": "gte", "bin_value_c": 27, "model_probability": 0.3}]
        self.assertEqual(median_bucket(b, "model_probability"), 26)  # cumulative crosses 0.5 at 26

    def test_forecasts_consensus_is_median(self):
        rows = [{"eccc_forecast_high_c": 30, "weather_forecast_max_c": 29, "open_meteo_max_c": 28}]
        out = forecasts_from_rows(rows)
        self.assertEqual(out["consensus"], 29)  # median(28,29,30)

    def test_source_calibration_bias_and_hit(self):
        records = [
            {"forecasts": {"eccc": 29}, "settlement": 29},   # exact
            {"forecasts": {"eccc": 29}, "settlement": 27},   # forecast over-called by 2
        ]
        cal = source_calibration(records, "eccc")
        self.assertEqual(cal["n"], 2)
        self.assertAlmostEqual(cal["bias"], (0 + -2) / 2)    # realized - forecast
        self.assertAlmostEqual(cal["mae"], 1.0)
        self.assertAlmostEqual(cal["hit_rate"], 0.5)


class TestDayRecordAndVerdict(unittest.TestCase):
    def test_selects_first_snapshot_at_or_after_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            slug = "highest-temperature-in-toronto-on-june-3-2026"
            folder = write_day(tmp, slug, [
                ("2026-06-03T06:00:00", {"eccc": 30}, bands(0.2, 0.8)),
                ("2026-06-03T09:00:00", {"eccc": 29}, bands(0.2, 0.8)),
            ], settle=29)
            rec = day_record(folder, 9, {}, {"2026-06-03": 29})
            self.assertEqual(rec["captured_at_local"], "2026-06-03T09:00:00")  # first >= 9
            self.assertEqual(rec["forecast_bucket"], 29)
            self.assertTrue(rec["reached"])                                     # 29 >= 29

    def test_costing_verdict_when_reached_but_model_low(self):
        with tempfile.TemporaryDirectory() as tmp:
            folders = []
            for day in ("may-30-2026", "may-31-2026", "june-1-2026"):
                slug = f"highest-temperature-in-toronto-on-{day}"
                folders.append(str(write_day(tmp, slug, [
                    (f"2026-05-{day[4:6] if False else '30'}T09:00:00", {"eccc": 29, "weather_com": 29, "open_meteo": 29},
                     bands(model_gte29=0.2, market_gte29=0.8)),
                ], settle=29)))
            overrides = {"2026-05-30": 29, "2026-05-31": 29, "2026-06-01": 29}
            results = run(folders, [9], daily_summary_path="missing.csv", overrides=overrides, verdict_cutoff=9)
            v = results["verdict"]
            self.assertEqual(v["headline"], "SKEPTICISM IS COSTING")
            self.assertAlmostEqual(v["reach_rate"], 1.0)
            self.assertAlmostEqual(v["model_reach"], 0.2)
            self.assertGreater(v["gap"], 0.15)

    def test_justified_verdict_when_forecast_overcalls(self):
        with tempfile.TemporaryDirectory() as tmp:
            folders = []
            for day in ("may-30-2026", "may-31-2026"):
                slug = f"highest-temperature-in-toronto-on-{day}"
                folders.append(str(write_day(tmp, slug, [
                    ("2026-05-30T09:00:00", {"eccc": 29, "weather_com": 29, "open_meteo": 29},
                     bands(model_gte29=0.5, market_gte29=0.6)),
                ], settle=27)))  # forecast 29 but realized 27 -> over-called, not reached
            overrides = {"2026-05-30": 27, "2026-05-31": 27}
            results = run(folders, [9], "missing.csv", overrides, 9)
            v = results["verdict"]
            self.assertEqual(v["headline"], "SKEPTICISM IS JUSTIFIED")
            self.assertAlmostEqual(v["reach_rate"], 0.0)   # 27 < 29 never reached
            self.assertLess(v["gap"], -0.15)
            # consensus forecast over-called: realized - forecast = 27 - 29 = -2
            self.assertAlmostEqual(v["consensus_bias"], -2.0)


if __name__ == "__main__":
    unittest.main()
