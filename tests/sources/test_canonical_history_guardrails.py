import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath("src"))

from canonical_history_guardrails import (  # noqa: E402
    build_ghcnh_composite_view,
    canonical_daily_violations,
    read_daily_rows,
    write_composite_daily_csv,
)
from supplemental_station_validation import source_fingerprint  # noqa: E402


class TestCanonicalHistoryGuardrails(unittest.TestCase):
    def write_daily(self, path, rows, extra_fields=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "schema_version",
            "source",
            "source_role",
            "canonical_market_id",
            "supplemental_source_id",
            "supplemental_station_id",
            "market_id",
            "city",
            "station",
            "station_name",
            "local_date",
            "temperature_unit",
            "row_count",
            "max_temp",
            "max_temp_bucket",
        ]
        for field in extra_fields or []:
            if field not in fieldnames:
                fieldnames.append(field)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    "schema_version": "historical_daily_native_v1",
                    "source": "noaa_ghcnh",
                    "source_role": "canonical",
                    "canonical_market_id": "kxxx",
                    "supplemental_source_id": "",
                    "supplemental_station_id": "",
                    "market_id": "kxxx",
                    "city": "Test City",
                    "station_name": "Station",
                    "temperature_unit": "C",
                    "row_count": 24,
                    **row,
                })

    def supplemental_source(self, root):
        return {
            "market_id": "kxxx",
            "source_id": "ghcnh_kxxx_nearby",
            "source_type": "noaa_ghcnh",
            "source_role": "supplemental",
            "station_id": "CAN00000002",
            "station_name": "Nearby",
            "root_path": str(root),
            "latitude": 10.0,
            "longitude": 20.0,
            "elevation_m": 100.0,
            "distance_from_canonical_km": 0.5,
            "canonical_market_id": "kxxx",
            "canonical_station_id": "KXXX",
            "validation_status": "candidate",
            "adopted_date_windows": [{
                "start": "2020-05-20",
                "end": "2020-05-20",
                "reason": "unit test",
            }],
            "reason_for_adoption": "unit test",
        }

    def validation_report(self, source):
        return {
            "schema_version": "supplemental_station_validation_v0.1",
            "artifact_path": "unit-test.json",
            "sources": [{
                "source_id": source["source_id"],
                "source_fingerprint": source_fingerprint(source),
                "promotion_state": "validated_supplemental",
                "validation_window": {"start": "2020-05-20", "end": "2020-05-20"},
                "validated_weather_regimes": ["mild"],
                "gates": [{"name": "distance_from_canonical", "severity": "hard", "ok": True}],
            }],
        }

    def test_canonical_daily_guardrail_flags_supplemental_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = SimpleNamespace(id="kxxx", icao="KXXX", city_label="Test City")
            station = root / "data/noaa_ghcnh/kxxx/station.json"
            station.parent.mkdir(parents=True, exist_ok=True)
            station.write_text('{"GHCN_ID":"CAN00000001"}\n', encoding="utf-8")
            self.write_daily(
                root / "data/noaa_ghcnh/kxxx/daily/daily_summary.csv",
                [{
                    "source_role": "supplemental",
                    "supplemental_source_id": "ghcnh_kxxx_nearby",
                    "supplemental_station_id": "CAN00000002",
                    "station": "CAN00000002",
                    "local_date": "2020-05-20",
                    "max_temp": 20.0,
                    "max_temp_bucket": 20,
                }],
            )
            registry = {
                "schema_version": "supplemental_station_registry_v0.1",
                "sources": [self.supplemental_source(root / "data/noaa_ghcnh/kxxx_alt")],
            }
            with patch("canonical_history_guardrails.REPO_ROOT", root):
                report = canonical_daily_violations(spec, "ghcnh", registry=registry)

        types = {row["type"] for row in report["violations"]}
        self.assertIn("non_canonical_source_role", types)
        self.assertIn("supplemental_lineage_in_canonical_csv", types)
        self.assertIn("registered_supplemental_station_in_canonical_csv", types)
        self.assertIn("unexpected_canonical_station", types)

    def test_composite_view_keeps_supplemental_rows_out_of_canonical_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = SimpleNamespace(id="kxxx", icao="KXXX", city_label="Test City")
            station = root / "data/noaa_ghcnh/kxxx/station.json"
            station.parent.mkdir(parents=True, exist_ok=True)
            station.write_text('{"GHCN_ID":"CAN00000001"}\n', encoding="utf-8")
            canonical_path = root / "data/noaa_ghcnh/kxxx/daily/daily_summary.csv"
            supplemental_root = root / "data/noaa_ghcnh/kxxx_alt"
            supplemental_path = supplemental_root / "daily/daily_summary.csv"
            self.write_daily(canonical_path, [{
                "station": "CAN00000001",
                "local_date": "2020-05-20",
                "max_temp": 20.0,
                "max_temp_bucket": 20,
            }])
            self.write_daily(supplemental_path, [{
                "source_role": "supplemental",
                "supplemental_source_id": "ghcnh_kxxx_nearby",
                "supplemental_station_id": "CAN00000002",
                "station": "CAN00000002",
                "local_date": "2020-05-20",
                "max_temp": 20.2,
                "max_temp_bucket": 20,
            }])
            source = self.supplemental_source(supplemental_root)
            registry = {"schema_version": "supplemental_station_registry_v0.1", "sources": [source]}
            with patch("canonical_history_guardrails.REPO_ROOT", root):
                rows = build_ghcnh_composite_view(
                    spec,
                    registry=registry,
                    validation_report=self.validation_report(source),
                    start="2020-05-20",
                    end="2020-05-20",
                )
                out = root / "composite.csv"
                write_composite_daily_csv(out, rows)
                canonical_rows = read_daily_rows(canonical_path)
                composite_rows = read_daily_rows(out)

        self.assertEqual(len(canonical_rows), 1)
        self.assertNotIn("lineage_source_role", canonical_rows[0])
        self.assertEqual(len(composite_rows), 2)
        self.assertEqual(
            {row["lineage_source_role"] for row in composite_rows},
            {"canonical", "supplemental"},
        )
        supplemental = [row for row in composite_rows if row["lineage_source_role"] == "supplemental"][0]
        self.assertEqual(supplemental["lineage_source_id"], "ghcnh_kxxx_nearby")
        self.assertEqual(supplemental["lineage_distance_from_canonical_km"], "0.5")


if __name__ == "__main__":
    unittest.main()
