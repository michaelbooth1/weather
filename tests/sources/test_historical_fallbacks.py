import os
import sys
import unittest
from weather.market.market_registry import spec_for_id  # noqa: E402
from weather.sources.historical_fallbacks import (  # noqa: E402
    build_meteostat_hourly_url,
    build_nasa_power_hourly_params,
    fallback_coverage_bias_report,
    fallback_feature_promotion_gate,
    fallback_source_policy,
    normalize_meteostat_hourly_csv,
    normalize_nasa_power_payload,
    parse_meteostat_station_metadata,
    render_fallback_coverage_bias_markdown,
    station_discovery_report,
)


class TestHistoricalFallbacks(unittest.TestCase):
    def test_meteostat_station_discovery_report_ranks_candidates(self):
        spec = spec_for_id("nyc")
        stations = parse_meteostat_station_metadata("""id,name,icao,wmo,country,latitude,longitude,hourly_start,hourly_end
72503,New York LaGuardia,KLGA,72503,US,40.779,-73.880,1973-01-01,2026-06-01
99999,Far Away,KZZZ,99999,US,35.0,-100.0,2000-01-01,2020-01-01
""")

        report = station_discovery_report([spec], stations)
        market = report["markets"][0]

        self.assertEqual(report["schema_version"], "historical_fallbacks_v0.1")
        self.assertEqual(market["source"], "meteostat")
        self.assertEqual(market["canonical_match"]["icao"], "KLGA")
        self.assertEqual(market["candidates"][0]["station_id"], "72503")
        self.assertEqual(market["allowed_role"], "supplemental_discovery")

    def test_meteostat_hourly_normalization_preserves_source_columns(self):
        spec = spec_for_id("nyc")
        url = build_meteostat_hourly_url(2025, "72503")
        rows = normalize_meteostat_hourly_csv(
            """time,temp,dwpt,rhum,prcp,wdir,wspd,pres,cldc,coco,temp_source,prcp_source
2025-06-14T12:00,28.0,18.0,55,0.0,180,12,1012,20,1,isd_lite,isd_lite
2025-06-14T13:00,29.0,18.5,52,0.0,190,14,1011,25,1,dwd_mosmix,isd_lite
""",
            spec,
            "72503",
        )

        self.assertEqual(url, "https://data.meteostat.net/hourly/2025/72503.csv.gz")
        self.assertEqual(rows[0]["source"], "meteostat")
        self.assertFalse(rows[0]["allowed_as_settlement_label"])
        self.assertEqual(rows[0]["source_class"], "observed_station")
        self.assertEqual(rows[1]["source_class"], "mixed")
        self.assertTrue(rows[1]["model_filled"])
        self.assertEqual(rows[1]["source_columns"]["temp_source"], "dwd_mosmix")
        self.assertAlmostEqual(rows[0]["temp_native"], 82.4)

    def test_nasa_power_params_and_fill_value_normalization(self):
        spec = spec_for_id("atlanta")
        params = build_nasa_power_hourly_params(spec, "2025-06-01", "2025-06-01")
        payload = {
            "properties": {
                "parameter": {
                    "ALLSKY_SFC_SW_DWN": {"2025060112": 500.0, "2025060113": -999.0},
                    "CLRSKY_SFC_SW_DWN": {"2025060112": 700.0, "2025060113": 750.0},
                    "T2M": {"2025060112": 28.0, "2025060113": 29.0},
                    "T2MDEW": {"2025060112": 18.0, "2025060113": 18.5},
                    "RH2M": {"2025060112": 55.0, "2025060113": 54.0},
                    "PRECTOTCORR": {"2025060112": 0.0, "2025060113": 0.2},
                    "PS": {"2025060112": 100.5, "2025060113": 100.4},
                    "WS10M": {"2025060112": 4.0, "2025060113": 5.0},
                    "WD10M": {"2025060112": 180.0, "2025060113": 190.0},
                }
            }
        }

        normalized = normalize_nasa_power_payload(payload, spec)

        self.assertEqual(params["start"], "20250601")
        self.assertEqual(params["time-standard"], "LST")
        self.assertIn("ALLSKY_SFC_SW_DWN", params["parameters"])
        self.assertEqual(normalized["schema_version"], "historical_fallbacks_v0.1")
        self.assertFalse(normalized["allowed_as_settlement_label"])
        self.assertEqual(normalized["row_count"], 2)
        self.assertAlmostEqual(normalized["rows"][0]["temp_native"], 82.4)
        self.assertEqual(normalized["rows"][0]["pressure_hpa"], 1005.0)
        self.assertEqual(normalized["rows"][0]["wind_speed_kmh"], 14.4)
        self.assertIsNone(normalized["rows"][1]["solar_allsky_wh_m2"])
        self.assertEqual(normalized["fill_value_stats"]["ALLSKY_SFC_SW_DWN"]["fill_rate"], 0.5)

    def test_policy_disallows_canonical_truth_roles(self):
        policy = fallback_source_policy()

        self.assertIn("settlement_label", policy["sources"]["meteostat"]["disallowed_roles"])
        self.assertIn("canonical_observation_replacement", policy["sources"]["nasa_power"]["disallowed_roles"])
        self.assertTrue(policy["sources"]["nasa_power"]["requires_fill_value_audit"])

    def test_coverage_bias_report_compares_fallbacks_to_reference_sources_by_regime(self):
        fallback_rows = [
            {
                "market": "nyc",
                "source": "meteostat",
                "source_class": "observed_station",
                "local_date": "2025-06-14",
                "minute_of_day": 720,
                "temp_native": 82.0,
                "regime": "hot_clear",
            },
            {
                "market": "nyc",
                "source": "nasa_power",
                "local_date": "2025-06-14",
                "minute_of_day": 720,
                "temp_native": 81.0,
                "regime": "hot_clear",
            },
        ]
        reference_rows = [
            {"market": "nyc", "source": "wu", "local_date": "2025-06-14", "minute_of_day": 720, "temp_native": 80.0, "regime": "hot_clear"},
            {"market": "nyc", "source": "metar", "local_date": "2025-06-14", "minute_of_day": 720, "temp_native": 81.0, "regime": "hot_clear"},
            {"market": "nyc", "source": "ghcnh", "local_date": "2025-06-14", "minute_of_day": 720, "temp_native": 79.0, "regime": "hot_clear"},
            {"market": "nyc", "source": "reanalysis", "local_date": "2025-06-14", "minute_of_day": 720, "temp_native": 80.5, "regime": "hot_clear"},
            {
                "market": "nyc",
                "source": "ghcnh_supplemental__nearby",
                "source_role": "supplemental",
                "local_date": "2025-06-14",
                "minute_of_day": 720,
                "temp_native": 80.2,
                "regime": "hot_clear",
            },
        ]

        report = fallback_coverage_bias_report(fallback_rows, reference_rows)
        comparisons = {
            (row["fallback_source"], row["reference_source"], row["regime"]): row
            for row in report["comparisons"]
        }
        markdown = render_fallback_coverage_bias_markdown(report)

        self.assertEqual(report["summary"]["fallback_sources"], ["meteostat", "nasa_power"])
        self.assertEqual(
            report["summary"]["reference_sources"],
            ["ghcnh", "metar", "reanalysis", "validated_supplemental", "wu"],
        )
        self.assertEqual(report["summary"]["comparable_pairs"], 20)
        meteostat_wu = comparisons[("meteostat", "wu", "hot_clear")]
        self.assertEqual(meteostat_wu["coverage_rate"], 1.0)
        self.assertEqual(meteostat_wu["bias_fallback_minus_reference"], 2.0)
        self.assertEqual(meteostat_wu["mae_fallback_vs_reference"], 2.0)
        self.assertEqual(comparisons[("nasa_power", "validated_supplemental", "hot_clear")]["overlap_rows"], 1)
        self.assertIn("validated_supplemental", markdown)

    def test_fallback_feature_promotion_gate_requires_replay_lift_and_safe_roles(self):
        blocked = fallback_feature_promotion_gate(
            {
                "summary": {"scored_rows": 50},
                "baseline": {"brier": 0.19},
                "candidate": {"brier": 0.18},
                "feature_roles": ["energy_budget_context", "settlement_label"],
            },
            min_scored_rows=30,
        )
        ok = fallback_feature_promotion_gate(
            {
                "summary": {"scored_rows": 50},
                "baseline": {"brier": 0.19},
                "candidate": {"brier": 0.18},
                "feature_roles": ["energy_budget_context", "source_trust"],
            },
            min_scored_rows=30,
        )

        self.assertFalse(blocked["ok"])
        self.assertIn("disallowed_truth_role", blocked["reasons"])
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["status"], "promotable")
        self.assertAlmostEqual(ok["brier_improvement"], 0.01)


if __name__ == "__main__":
    unittest.main()
