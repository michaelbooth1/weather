import csv
import json
import pickle
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from weather.reporting.source_family_inventory import (
    build_source_family_inventory,
    item27_reanalysis_ablation_evidence,
    market_expansion_scorecard,
    reanalysis_promotion_lane,
    write_outputs,
)
from weather.market.market_microstructure_features import CLOB_MODEL_FEATURE_COLUMNS
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
                candidate_replay_json=backtest_root / "missing_candidate_replay.json",
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
                candidate_replay_json=backtest_root / "missing_candidate_replay.json",
                locations_config=locations_config,
                item27_reanalysis_paths={},
                item27_required_markets=[],
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

    def test_clob_parity_accepts_structural_blanks_when_availability_is_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = root / "snapshots"
            backtest_root = root / "backtest"
            folder = snapshots_root / "highest-temperature-in-nyc-on-june-18-2026"
            folder.mkdir(parents=True)
            unavailable = {
                "snapshot_id": "s1",
                "captured_at_utc": "2026-06-18T18:10:00+00:00",
                "market_id": "nyc",
                **{column: "" for column in CLOB_MODEL_FEATURE_COLUMNS},
            }
            unavailable["clob_feature_available"] = "0"
            available = {
                "snapshot_id": "s2",
                "captured_at_utc": "2026-06-18T18:20:00+00:00",
                "market_id": "nyc",
                **{column: "" for column in CLOB_MODEL_FEATURE_COLUMNS},
            }
            available.update({
                "clob_feature_available": "1",
                "clob_book_age_seconds": "5",
                "clob_best_bid": "0.48",
                "clob_best_ask": "0.52",
                "clob_depth_1pct_total": "100",
                "clob_depth_5pct_total": "200",
                "clob_depth_all_total": "300",
                "clob_price_history_available": "0",
                "clob_price_history_points_300s": "0",
                "clob_ws_event_count_60s": "0",
                "clob_ws_event_count_300s": "0",
            })
            write_csv(folder / "clob_features_long.csv", [unavailable, available])
            write_csv(folder / "order_books_summary.csv", [{"market_id": "nyc", "midpoint": "0.50"}])
            write_csv(folder / "price_history.csv", [{"market_id": "nyc", "price": "0.50"}])
            write_csv(folder / "market_ws_events.csv", [{"market_id": "nyc", "event_type": "price_change"}])
            ablation_json = backtest_root / "source_family_ablation.json"
            ablation_json.parent.mkdir(parents=True)
            ablation_json.write_text(
                json.dumps(
                    {
                        "variants": [
                            {"variant": "clob_microstructure", "n": 2, "days": 1, "delta": 0.01},
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
                candidate_replay_json=backtest_root / "missing_candidate_replay.json",
                locations_config=locations_config,
                item27_reanalysis_paths={},
                item27_required_markets=[],
                generated_at_utc="2026-06-18T20:00:00+00:00",
            )
            rows = {row["family_id"]: row for row in payload["inventory"]}
            clob = rows["clob_microstructure"]

        self.assertEqual(clob["lineage_status"], "PASS")
        self.assertEqual(clob["train_serve_parity_status"], "PASS")
        self.assertGreater(clob["feature_missingness"]["missing_rate"], 0.5)
        self.assertEqual(clob["promotion_decision"]["status"], "PROMOTION_CANDIDATE")

    def test_promotion_preflight_only_blocks_active_artifact_inputs(self):
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
                        "source": "open_meteo",
                        "ok": "True",
                        "status": "fresh",
                    }
                ],
            )
            write_csv(
                folder / "forecast_payloads_long.csv",
                [
                    {
                        "snapshot_id": "s1",
                        "captured_at_local": "2026-06-18T14:10:00-04:00",
                        "event_slug": folder.name,
                        "source": "open_meteo",
                        "status": "fresh",
                        "raw_payload_path": "forecast_payloads/s1_open_meteo.json",
                    }
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
                        "band_value": "91",
                    }
                ],
            )
            ablation_json = backtest_root / "source_family_ablation.json"
            ablation_json.parent.mkdir(parents=True)
            ablation_json.write_text(
                json.dumps({"variants": [{"variant": "all_forecasts", "n": 4, "days": 1, "delta": 0.01}]}),
                encoding="utf-8",
            )
            artifact = backtest_root / "artifact.pkl"
            with artifact.open("wb") as handle:
                pickle.dump({"models": {"7": {"feature_names": ["band_value"]}}}, handle)
            candidate_replay = backtest_root / "candidate_replay.json"
            candidate_replay.write_text(json.dumps({"artifact": {"path": str(artifact)}}), encoding="utf-8")
            locations_config = root / "locations.json"
            locations_config.write_text(json.dumps({"locations": []}), encoding="utf-8")

            payload = build_source_family_inventory(
                snapshots_root=snapshots_root,
                backtest_root=backtest_root,
                ablation_json=ablation_json,
                candidate_replay_json=candidate_replay,
                locations_config=locations_config,
                item27_reanalysis_paths={},
                item27_required_markets=[],
                generated_at_utc="2026-06-18T20:00:00+00:00",
            )
            rows = {row["family_id"]: row for row in payload["inventory"]}

        self.assertEqual(payload["active_model_usage"]["status"], "PRESENT")
        self.assertFalse(rows["forecast_baseline"]["model_influence"])
        self.assertFalse(rows["nws_grid"]["model_influence"])
        self.assertEqual(rows["nws_grid"]["active_model_usage_status"], "NOT_USED_BY_ACTIVE_ARTIFACT")
        self.assertEqual(rows["nws_grid"]["promotion_decision"]["status"], "BLOCK_LINEAGE")
        self.assertEqual(payload["promotion_preflight"]["status"], "PASS")

    def test_promotion_preflight_blocks_missing_lineage_for_active_artifact_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = root / "snapshots"
            backtest_root = root / "backtest"
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
                        "nws_grid_high": "92",
                    }
                ],
            )
            ablation_json = backtest_root / "source_family_ablation.json"
            ablation_json.parent.mkdir(parents=True)
            ablation_json.write_text(
                json.dumps({"variants": [{"variant": "nws_grid", "n": 4, "days": 1, "delta": 0.01}]}),
                encoding="utf-8",
            )
            artifact = backtest_root / "artifact.pkl"
            with artifact.open("wb") as handle:
                pickle.dump({"models": {"7": {"feature_names": ["nws_grid_high"]}}}, handle)
            candidate_replay = backtest_root / "candidate_replay.json"
            candidate_replay.write_text(json.dumps({"artifact": {"path": str(artifact)}}), encoding="utf-8")
            locations_config = root / "locations.json"
            locations_config.write_text(json.dumps({"locations": []}), encoding="utf-8")

            payload = build_source_family_inventory(
                snapshots_root=snapshots_root,
                backtest_root=backtest_root,
                ablation_json=ablation_json,
                candidate_replay_json=candidate_replay,
                locations_config=locations_config,
                item27_reanalysis_paths={},
                item27_required_markets=[],
                generated_at_utc="2026-06-18T20:00:00+00:00",
            )
            rows = {row["family_id"]: row for row in payload["inventory"]}

        self.assertTrue(rows["nws_grid"]["model_influence"])
        self.assertEqual(rows["nws_grid"]["active_model_feature_columns"], ["nws_grid_high"])
        self.assertEqual(payload["promotion_preflight"]["status"], "BLOCK")
        self.assertEqual(payload["promotion_preflight"]["blocked_families"], ["nws_grid"])

    def test_promotion_preflight_blocks_reanalysis_artifact_lane_that_allows_gate_quarantine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = root / "snapshots"
            backtest_root = root / "backtest"
            reanalysis_root = root / "reanalysis"
            for icao, market_id in [("kaus", "austin"), ("klga", "nyc")]:
                row = {
                    "local_date": "2026-06-18",
                    "market_id": market_id,
                }
                row.update({column: "1.0" for column in REANALYSIS_SYNOPTIC_FEATURE_COLUMNS})
                write_csv(
                    reanalysis_root / icao / "features" / "reanalysis_synoptic_features.csv",
                    [row],
                )
            ablation_paths = {
                "austin": root / "austin_item27.json",
                "nyc": root / "nyc_item27.json",
            }
            ablation_paths["austin"].write_text(
                json.dumps({
                    "promotion_decisions": [
                        {
                            "family": "reanalysis_synoptic",
                            "n": 3,
                            "full_brier": 0.20,
                            "ablated_brier": 0.26,
                            "delta_brier": 0.06,
                        }
                    ]
                }),
                encoding="utf-8",
            )
            ablation_paths["nyc"].write_text(
                json.dumps({
                    "promotion_decisions": [
                        {
                            "family": "reanalysis_synoptic",
                            "n": 3,
                            "full_brier": 0.30,
                            "ablated_brier": 0.25,
                            "delta_brier": -0.05,
                        }
                    ]
                }),
                encoding="utf-8",
            )
            artifact = backtest_root / "artifact.pkl"
            artifact.parent.mkdir(parents=True)
            with artifact.open("wb") as handle:
                pickle.dump(
                    {
                        "models": {
                            "7": {
                                "feature_names": ["reanalysis_prev_day_max_temp"],
                            }
                        },
                        "reanalysis_promotion_lane": {
                            "status": "PARTIAL_POSITIVE_MARKET_SHADOW_LANE",
                            "policy": "unsafe_test",
                            "allowed_markets": ["austin", "nyc"],
                            "quarantined_markets": [],
                        },
                    },
                    handle,
                )
            candidate_replay = backtest_root / "candidate_replay.json"
            candidate_replay.write_text(json.dumps({"artifact": {"path": str(artifact)}}), encoding="utf-8")
            locations_config = root / "locations.json"
            locations_config.write_text(json.dumps({"locations": []}), encoding="utf-8")

            payload = build_source_family_inventory(
                snapshots_root=snapshots_root,
                reanalysis_root=reanalysis_root,
                backtest_root=backtest_root,
                candidate_replay_json=candidate_replay,
                locations_config=locations_config,
                item27_reanalysis_paths=ablation_paths,
                item27_required_markets=["austin", "nyc"],
                generated_at_utc="2026-06-18T20:00:00+00:00",
            )
            rows = {row["family_id"]: row for row in payload["inventory"]}
            reanalysis = rows["reanalysis_synoptic"]

        self.assertTrue(reanalysis["model_influence"])
        self.assertEqual(reanalysis["lineage_status"], "PASS")
        self.assertEqual(reanalysis["train_serve_parity_status"], "PASS")
        self.assertEqual(reanalysis["promotion_decision"]["status"], "PROMOTION_CANDIDATE")
        self.assertEqual(
            reanalysis["artifact_lane_consistency"]["status"],
            "BLOCK_ARTIFACT_ALLOWS_QUARANTINED_MARKETS",
        )
        self.assertEqual(payload["promotion_preflight"]["status"], "BLOCK")
        self.assertEqual(payload["promotion_preflight"]["blocked_families"], ["reanalysis_synoptic"])

    def test_promotion_preflight_ignores_imputer_dropped_all_missing_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = root / "snapshots"
            backtest_root = root / "backtest"
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
                        "nws_grid_high": "92",
                        "band_value": "91",
                    }
                ],
            )
            ablation_json = backtest_root / "source_family_ablation.json"
            ablation_json.parent.mkdir(parents=True)
            ablation_json.write_text(
                json.dumps({"variants": [{"variant": "nws_grid", "n": 4, "days": 1, "delta": 0.01}]}),
                encoding="utf-8",
            )
            artifact = backtest_root / "artifact.pkl"
            with artifact.open("wb") as handle:
                pickle.dump(
                    {
                        "models": {
                            "7": {
                                "feature_names": ["nws_grid_high", "band_value"],
                                "imputer": SimpleNamespace(statistics_=[float("nan"), 91.0]),
                            }
                        }
                    },
                    handle,
                )
            candidate_replay = backtest_root / "candidate_replay.json"
            candidate_replay.write_text(json.dumps({"artifact": {"path": str(artifact)}}), encoding="utf-8")
            locations_config = root / "locations.json"
            locations_config.write_text(json.dumps({"locations": []}), encoding="utf-8")

            payload = build_source_family_inventory(
                snapshots_root=snapshots_root,
                backtest_root=backtest_root,
                ablation_json=ablation_json,
                candidate_replay_json=candidate_replay,
                locations_config=locations_config,
                item27_reanalysis_paths={},
                item27_required_markets=[],
                generated_at_utc="2026-06-18T20:00:00+00:00",
            )
            rows = {row["family_id"]: row for row in payload["inventory"]}

        self.assertFalse(rows["nws_grid"]["model_influence"])
        self.assertEqual(rows["nws_grid"]["active_model_feature_columns"], [])
        self.assertEqual(rows["nws_grid"]["active_model_usage_status"], "NOT_USED_BY_ACTIVE_ARTIFACT")
        self.assertEqual(payload["promotion_preflight"]["status"], "PASS")

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
        self.assertEqual(evidence["positive_markets"], ["atlanta"])
        self.assertEqual(evidence["blocked_markets"], ["toronto"])
        self.assertEqual(
            [
                (row["market_id"], row["rows"], row["decision"])
                for row in evidence["market_details"]
            ],
            [("atlanta", 3, "promote"), ("toronto", 1, "block")],
        )

    def test_reanalysis_promotion_lane_quarantines_blocked_markets(self):
        lane = reanalysis_promotion_lane(
            {
                "status": "PRESENT",
                "market_details": [
                    {"market_id": "austin", "delta_brier": 0.042},
                    {"market_id": "seattle", "delta_brier": 0.0015},
                    {"market_id": "toronto", "delta_brier": -0.01},
                ],
            }
        )

        self.assertEqual(lane["status"], "PARTIAL_POSITIVE_MARKET_SHADOW_LANE")
        self.assertEqual(lane["policy"], "positive_markets_only")
        self.assertEqual(lane["allowed_markets"], ["austin", "seattle"])
        self.assertEqual(lane["quarantined_markets"], ["toronto"])
        self.assertEqual(lane["thin_margin_markets"], ["seattle"])

    def test_report_renders_reanalysis_market_gate_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "generated_at_utc": "2026-06-18T20:00:00+00:00",
                "status": "PASS",
                "summary": {},
                "inventory": [
                    {
                        "family_id": "reanalysis_synoptic",
                        "lineage_status": "PASS",
                        "train_serve_parity_status": "PASS",
                        "model_influence": False,
                        "active_model_feature_count": 0,
                        "live_only_policy": "historical_sidecar_required",
                        "feature_missingness": {"missing_rate": 0.48},
                        "promotion_decision": {"status": "PROMOTION_CANDIDATE"},
                        "promotion_lane": {
                            "status": "PARTIAL_POSITIVE_MARKET_SHADOW_LANE",
                            "policy": "positive_markets_only",
                            "allowed_markets": ["austin"],
                            "quarantined_markets": ["toronto"],
                            "thin_margin_markets": [],
                            "reason": "Mixed per-market gates.",
                            "action": "Train or shadow only the allowed markets.",
                        },
                        "ablation": {
                            "status": "PRESENT",
                            "market_details": [
                                {
                                    "market_id": "austin",
                                    "rows": 5,
                                    "full_brier": 0.20,
                                    "ablated_brier": 0.25,
                                    "delta_brier": 0.05,
                                    "decision": "promote",
                                },
                                {
                                    "market_id": "toronto",
                                    "rows": 7,
                                    "full_brier": 0.40,
                                    "ablated_brier": 0.39,
                                    "delta_brier": -0.01,
                                    "decision": "block",
                                },
                            ],
                        },
                    }
                ],
                "promotion_preflight": {},
                "market_expansion_scorecard": {},
            }
            _json_path, report_path = write_outputs(
                payload,
                json_out=root / "inventory.json",
                report_out=root / "inventory.md",
            )

            report = report_path.read_text(encoding="utf-8")

        self.assertIn("## Reanalysis Market Gates", report)
        self.assertIn("## Reanalysis Promotion Lane", report)
        self.assertIn("| Allowed markets | austin |", report)
        self.assertIn("| Quarantined markets | toronto |", report)
        self.assertIn("| austin | 5 | 0.2000 | 0.2500 | +0.0500 | promote |", report)
        self.assertIn("| toronto | 7 | 0.4000 | 0.3900 | -0.0100 | block |", report)


if __name__ == "__main__":
    unittest.main()
