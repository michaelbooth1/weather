import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.source_family_inventory import (
    build_source_family_inventory,
    item27_reanalysis_ablation_evidence,
    market_expansion_scorecard,
    write_outputs,
)
from weather.model.feature_store import REANALYSIS_SYNOPTIC_FEATURE_COLUMNS


def write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class TestSourceFamilyInventory(unittest.TestCase):
    def test_builds_inventory_with_lineage_missingness_and_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = root / "snapshots"
            backtest_root = root / "backtest"
            folder = snapshots_root / "highest-temperature-in-nyc-on-june-18-2026"
            folder.mkdir(parents=True)
            write_csv(
                folder / "source_status_long.csv",
                [
                    {
                        "snapshot_id": "s1",
                        "captured_at_local": "2026-06-18T14:10:00-04:00",
                        "event_slug": folder.name,
                        "source": "nws_grid",
                        "ok": "True",
                        "status": "fresh",
                        "source_family": "nws_grid",
                    },
                    {
                        "snapshot_id": "s1",
                        "captured_at_local": "2026-06-18T14:10:00-04:00",
                        "event_slug": folder.name,
                        "source": "nws_hourly",
                        "ok": "True",
                        "status": "fresh",
                        "source_family": "nws_hourly",
                    },
                    {
                        "snapshot_id": "s1",
                        "captured_at_local": "2026-06-18T14:10:00-04:00",
                        "event_slug": folder.name,
                        "source": "open_meteo",
                        "ok": "True",
                        "status": "fresh",
                        "source_family": "open_meteo",
                    },
                ],
            )
            write_csv(
                folder / "forecast_payloads_long.csv",
                [
                    {
                        "snapshot_id": "s1",
                        "captured_at_local": "2026-06-18T14:10:00-04:00",
                        "event_slug": folder.name,
                        "source": "nws_grid",
                        "status": "fresh",
                        "source_family": "nws_grid",
                        "raw_payload_path": "forecast_payloads/s1_nws_grid.json",
                    },
                    {
                        "snapshot_id": "s1",
                        "captured_at_local": "2026-06-18T14:10:00-04:00",
                        "event_slug": folder.name,
                        "source": "nws_hourly",
                        "status": "fresh",
                        "source_family": "nws_hourly",
                        "raw_payload_path": "forecast_payloads/s1_nws_hourly.json",
                    },
                    {
                        "snapshot_id": "s1",
                        "captured_at_local": "2026-06-18T14:10:00-04:00",
                        "event_slug": folder.name,
                        "source": "open_meteo",
                        "status": "fresh",
                        "source_family": "open_meteo",
                        "raw_payload_path": "forecast_payloads/s1_open_meteo.json",
                    },
                ],
            )
            write_csv(
                folder / "features_long.csv",
                [
                    {
                        "snapshot_id": "s1",
                        "captured_at_local": "2026-06-18T14:10:00-04:00",
                        "event_slug": folder.name,
                        "market_id": "nyc",
                        "forecast_high": "91",
                        "forecast_gap": "2",
                        "forecast_source_count": "3",
                        "forecast_disagreement": "1.5",
                        "forecast_peak_hour": "15",
                        "nws_grid_high": "92",
                        "nws_grid_vs_forecast_high": "1",
                    },
                    {
                        "snapshot_id": "s2",
                        "captured_at_local": "2026-06-18T15:10:00-04:00",
                        "event_slug": folder.name,
                        "market_id": "nyc",
                        "forecast_high": "91",
                        "forecast_gap": "",
                        "forecast_source_count": "3",
                        "forecast_disagreement": "1.0",
                        "forecast_peak_hour": "",
                        "nws_grid_high": "",
                        "nws_grid_vs_forecast_high": "",
                    },
                ],
            )
            write_csv(
                folder / "clob_features_long.csv",
                [
                    {
                        "snapshot_id": "s1",
                        "captured_at_utc": "2026-06-18T18:10:00+00:00",
                        "market_id": "nyc",
                        "clob_feature_available": "1",
                        "clob_midpoint": "0.55",
                    }
                ],
            )
            write_csv(folder / "order_books_summary.csv", [{"market_id": "nyc", "midpoint": "0.55"}])
            write_csv(folder / "price_history.csv", [{"market_id": "nyc", "price": "0.55"}])
            write_csv(folder / "market_ws_events.csv", [{"market_id": "nyc", "event_type": "price_change"}])
            ablation_json = backtest_root / "source_family_ablation.json"
            ablation_json.parent.mkdir(parents=True)
            ablation_json.write_text(
                json.dumps(
                    {
                        "schema_version": "source_family_ablation_v0.1",
                        "variants": [
                            {"variant": "nws_grid", "n": 4, "days": 1, "delta": 0.02},
                            {"variant": "open_meteo", "n": 4, "days": 1, "delta": 0.01},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            locations_config = root / "locations.json"
            locations_config.write_text(json.dumps({"locations": []}), encoding="utf-8")

            payload = build_source_family_inventory(
                snapshots_root=snapshots_root,
                backtest_root=backtest_root,
                ablation_json=ablation_json,
                locations_config=locations_config,
                generated_at_utc="2026-06-18T20:00:00+00:00",
            )
            json_out, report_out = write_outputs(
                payload,
                json_out=backtest_root / "source_family_inventory.json",
                report_out=backtest_root / "source_family_inventory_report.md",
            )
            rows = {row["family_id"]: row for row in payload["inventory"]}
            json_exists = Path(json_out).exists()
            report_text = Path(report_out).read_text(encoding="utf-8")

        self.assertEqual(payload["schema_version"], "source_family_inventory_v0.1")
        self.assertEqual(payload["status"], "BLOCK")
        self.assertIn("nws_grid", rows)
        self.assertEqual(rows["nws_grid"]["lineage_status"], "PASS")
        self.assertEqual(rows["nws_grid"]["ablation"]["status"], "PRESENT")
        self.assertTrue(rows["nws_grid"]["live_only"])
        self.assertTrue(rows["nws_grid"]["feature_missingness"]["by_market"])
        self.assertTrue(rows["nws_grid"]["feature_missingness"]["by_cutoff_hour"])
        self.assertIn("clob_microstructure", rows)
        self.assertIn("clob_feature_available", rows["clob_microstructure"]["feature_columns_present"])
        self.assertGreater(payload["promotion_preflight"]["blocked_family_count"], 0)
        self.assertTrue(json_exists)
        self.assertIn("Source Family Inventory", report_text)

    def test_market_expansion_scorecard_blocks_incomplete_locations(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "locations.json"
            config_path.write_text(
                json.dumps(
                    {
                        "locations": [
                            {
                                "id": "new-city",
                                "city": "New City",
                                "country_code": "US",
                                "timezone": "America/New_York",
                                "market_unit": "F",
                                "coordinates": {"lat": 40.0, "lon": -73.0},
                                "settlement": {
                                    "station_id": "KNEW",
                                    "resolution_source_url": "https://example.test/history/KNEW",
                                    "source_type": "wunderground_history",
                                },
                                "live_source_plan": ["settlement_history", "open_meteo", "metar"],
                                "polymarket": {"latest_event_slug": "highest-temperature-in-new-city-on-june-18-2026"},
                            },
                            {
                                "id": "bad-city",
                                "city": "Bad City",
                                "timezone": "",
                                "market_unit": "F",
                                "coordinates": {},
                                "settlement": {},
                                "live_source_plan": ["open_meteo"],
                                "polymarket": {},
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            scorecard = market_expansion_scorecard(config_path)

        self.assertEqual(scorecard["candidate_count"], 2)
        self.assertEqual(scorecard["status"], "BLOCK")
        by_id = {row["location_id"]: row for row in scorecard["rows"]}
        self.assertEqual(by_id["new-city"]["status"], "PASS")
        self.assertEqual(by_id["bad-city"]["status"], "BLOCK")
        self.assertIn("settlement_station", by_id["bad-city"]["missing"])

    def test_reanalysis_sidecar_counts_as_historical_feature_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = root / "snapshots"
            backtest_root = root / "backtest"
            reanalysis_root = root / "reanalysis"
            folder = snapshots_root / "highest-temperature-in-nyc-on-june-18-2026"
            folder.mkdir(parents=True)
            write_csv(
                folder / "features_long.csv",
                [
                    {
                        "snapshot_id": "s1",
                        "captured_at_local": "2026-06-18T14:10:00-04:00",
                        "event_slug": folder.name,
                        "market_id": "nyc",
                        "reanalysis_synoptic_available": "",
                        "reanalysis_prev_day_max_temp": "",
                    }
                ],
            )
            sidecar_rows = []
            for local_date in ("2026-06-17", "2026-06-18"):
                row = {
                    "local_date": local_date,
                    "market_id": "nyc",
                }
                row.update({column: "1.0" for column in REANALYSIS_SYNOPTIC_FEATURE_COLUMNS})
                sidecar_rows.append(row)
            write_csv(
                reanalysis_root / "klga" / "features" / "reanalysis_synoptic_features.csv",
                sidecar_rows,
            )
            locations_config = root / "locations.json"
            locations_config.write_text(json.dumps({"locations": []}), encoding="utf-8")

            payload = build_source_family_inventory(
                snapshots_root=snapshots_root,
                reanalysis_root=reanalysis_root,
                backtest_root=backtest_root,
                locations_config=locations_config,
                generated_at_utc="2026-06-18T20:00:00+00:00",
            )
            rows = {row["family_id"]: row for row in payload["inventory"]}
            reanalysis = rows["reanalysis_synoptic"]

        self.assertEqual(reanalysis["lineage_status"], "PASS")
        self.assertEqual(reanalysis["train_serve_parity_status"], "PASS")
        self.assertEqual(reanalysis["feature_missingness"]["rows"], 2)
        self.assertEqual(reanalysis["feature_missingness"]["missing_rate"], 0.0)
        self.assertEqual(
            reanalysis["promotion_decision"]["status"],
            "BLOCK_MISSING_ABLATION",
        )

    def test_item27_reanalysis_evidence_requires_all_markets_and_aggregates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {
                "atlanta": root / "atlanta.json",
                "toronto": root / "toronto.json",
            }
            paths["atlanta"].write_text(
                json.dumps(
                    {
                        "promotion_decisions": [
                            {
                                "family": "reanalysis_synoptic",
                                "n": 3,
                                "full_brier": 0.20,
                                "ablated_brier": 0.26,
                                "delta_brier": 0.06,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            paths["toronto"].write_text(
                json.dumps(
                    {
                        "promotion_decisions": [
                            {
                                "family": "reanalysis_synoptic",
                                "n": 1,
                                "full_brier": 0.40,
                                "ablated_brier": 0.30,
                                "delta_brier": -0.10,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            evidence = item27_reanalysis_ablation_evidence(paths, required_markets=paths)
            missing = item27_reanalysis_ablation_evidence(
                paths,
                required_markets=["atlanta", "toronto", "nyc"],
            )

        self.assertIsNone(missing)
        self.assertEqual(evidence["variant"], "reanalysis_synoptic")
        self.assertEqual(evidence["n"], 4)
        self.assertAlmostEqual(evidence["base_brier"], 0.25)
        self.assertAlmostEqual(evidence["variant_brier"], 0.27)
        self.assertAlmostEqual(evidence["delta"], 0.02)
        self.assertEqual(evidence["days_source_helped"], 1)
        self.assertEqual(evidence["days_source_hurt"], 1)


if __name__ == "__main__":
    unittest.main()
