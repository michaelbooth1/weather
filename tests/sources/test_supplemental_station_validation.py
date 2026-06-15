import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath("src"))

from supplemental_station_validation import (  # noqa: E402
    build_validation_payload,
    promotion_gate_for_source,
    source_fingerprint,
    source_validation,
)


class TestSupplementalStationValidation(unittest.TestCase):
    def write_daily(self, path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["local_date", "max_temp", "max_temp_bucket"])
            writer.writeheader()
            writer.writerows(rows)

    def source(self, root):
        return {
            "market_id": "kxxx",
            "source_id": "ghcnh_kxxx_nearby",
            "source_type": "noaa_ghcnh",
            "source_role": "supplemental",
            "station_id": "USW00000002",
            "station_name": "Nearby AP",
            "root_path": str(root),
            "latitude": 10.0,
            "longitude": 20.0,
            "elevation_m": 3.0,
            "distance_from_canonical_km": 0.5,
            "canonical_market_id": "kxxx",
            "canonical_station_id": "KXXX",
            "validation_status": "candidate",
            "adopted_date_windows": [{
                "start": "2020-05-20",
                "end": "2020-05-22",
                "reason": "unit test",
            }],
            "reason_for_adoption": "unit test supplemental source",
        }

    def thresholds(self):
        return {
            "min_full_overlap_days": 3,
            "min_target_season_overlap_days": 3,
            "min_regime_overlap_days": 1,
            "min_missing_day_reduction": 1,
            "max_full_period_mae": 0.5,
            "max_target_season_mae": 0.5,
            "max_regime_mae": 0.5,
            "min_bucket_match_rate": 1.0,
            "max_abs_difference": 1.0,
            "max_distance_km": 5.0,
            "max_elevation_mismatch_m": 10.0,
            "max_weak_reference_mae": 2.0,
        }

    def write_fixture(self, root, candidate_rows=None):
        candidate_rows = candidate_rows or [
            {"local_date": "2020-05-20", "max_temp": "20.1", "max_temp_bucket": "20"},
            {"local_date": "2020-05-21", "max_temp": "21.0", "max_temp_bucket": "21"},
            {"local_date": "2020-05-22", "max_temp": "22.0", "max_temp_bucket": "22"},
        ]
        reference_rows = [
            {"local_date": "2020-05-20", "max_temp": "20.0", "max_temp_bucket": "20"},
            {"local_date": "2020-05-21", "max_temp": "21.0", "max_temp_bucket": "21"},
            {"local_date": "2020-05-22", "max_temp": "22.0", "max_temp_bucket": "22"},
        ]
        self.write_daily(root / "data/noaa_ghcnh/kxxx_alt/daily/daily_summary.csv", candidate_rows)
        self.write_daily(root / "data/wunderground/kxxx/daily/daily_summary.csv", reference_rows)
        self.write_daily(root / "data/metar/kxxx/daily/daily_summary.csv", reference_rows)
        self.write_daily(
            root / "data/noaa_ghcnh/kxxx/daily/daily_summary.csv",
            [{"local_date": "2020-05-19", "max_temp": "19.0", "max_temp_bucket": "19"}],
        )
        station_path = root / "data/noaa_ghcnh/kxxx/station.json"
        station_path.parent.mkdir(parents=True, exist_ok=True)
        station_path.write_text('{"ELEVATION":"2.0"}\n', encoding="utf-8")

    def test_source_validation_promotes_source_when_thresholds_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_fixture(root)
            spec = SimpleNamespace(id="kxxx", icao="KXXX", display_unit="C", city_label="Test City")
            source = self.source(root / "data/noaa_ghcnh/kxxx_alt")
            with patch("supplemental_station_validation.REPO_ROOT", root):
                row = source_validation(
                    spec,
                    source,
                    "2020-05-20",
                    "2020-05-22",
                    thresholds=self.thresholds(),
                )

        self.assertEqual(row["promotion_state"], "validated_supplemental")
        self.assertTrue(row["eligible_for_training"])
        self.assertEqual(row["coverage"]["target_season_missing_day_reduction"], 3)
        self.assertEqual(row["validated_weather_regimes"], ["mild"])

    def test_source_validation_rejects_large_bias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_fixture(root, candidate_rows=[
                {"local_date": "2020-05-20", "max_temp": "24.0", "max_temp_bucket": "24"},
                {"local_date": "2020-05-21", "max_temp": "25.0", "max_temp_bucket": "25"},
                {"local_date": "2020-05-22", "max_temp": "26.0", "max_temp_bucket": "26"},
            ])
            spec = SimpleNamespace(id="kxxx", icao="KXXX", display_unit="C", city_label="Test City")
            source = self.source(root / "data/noaa_ghcnh/kxxx_alt")
            with patch("supplemental_station_validation.REPO_ROOT", root):
                row = source_validation(
                    spec,
                    source,
                    "2020-05-20",
                    "2020-05-22",
                    thresholds=self.thresholds(),
                )

        self.assertEqual(row["promotion_state"], "rejected")
        self.assertFalse(row["eligible_for_training"])
        self.assertIn("wu_target_season_mae", {gate["name"] for gate in row["failures"]})

    def test_promotion_gate_fails_missing_and_stale_validation_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.source(Path(tmp) / "data/noaa_ghcnh/kxxx_alt")
            missing = promotion_gate_for_source(source, validation_report=None, validation_path=Path(tmp) / "missing.json")

            report = {
                "schema_version": "supplemental_station_validation_v0.1",
                "artifact_path": "unit-test.json",
                "sources": [{
                    "source_id": source["source_id"],
                    "source_fingerprint": source_fingerprint(source),
                    "promotion_state": "validated_supplemental",
                    "validation_window": {"start": "2020-05-20", "end": "2020-05-22"},
                    "validated_weather_regimes": ["mild"],
                    "gates": [{"name": "distance_from_canonical", "severity": "hard", "ok": True}],
                }],
            }
            stale_source = {**source, "station_name": "Renamed Station"}
            stale = promotion_gate_for_source(stale_source, validation_report=report)

        self.assertEqual(missing["status"], "FAIL")
        self.assertIn("missing current", missing["reason"])
        self.assertEqual(stale["status"], "FAIL")
        self.assertIn("fingerprint is stale", stale["reason"])

    def test_build_validation_payload_counts_promotion_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_fixture(root)
            spec = SimpleNamespace(id="kxxx", icao="KXXX", display_unit="C", city_label="Test City")
            source = self.source(root / "data/noaa_ghcnh/kxxx_alt")
            registry = {"schema_version": "supplemental_station_registry_v0.1", "sources": [source]}
            with patch("supplemental_station_validation.REPO_ROOT", root), patch(
                "supplemental_station_validation.all_specs",
                return_value=[spec],
            ):
                payload = build_validation_payload(
                    market_ids=["kxxx"],
                    start="2020-05-20",
                    end="2020-05-22",
                    registry=registry,
                    thresholds=self.thresholds(),
                )

        self.assertEqual(payload["source_count"], 1)
        self.assertEqual(payload["promotion_state_counts"], {"validated_supplemental": 1})


if __name__ == "__main__":
    unittest.main()
