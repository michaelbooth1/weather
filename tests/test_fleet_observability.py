import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.abspath("src"))

from collection_health import fleet_collection_health  # noqa: E402
from fleet_observability import (  # noqa: E402
    artifact_metadata,
    overall_status,
    trust_readiness,
)


class TestFleetObservability(unittest.TestCase):
    def test_fleet_collection_health_returns_one_row_per_registered_market(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-toronto-on-june-7-2026"
            folder.mkdir(parents=True)
            start = datetime(2026, 6, 7, 11, 0)
            pd.DataFrame([
                {
                    "snapshot_id": f"s{i}",
                    "captured_at_local": (start + timedelta(minutes=10 * i)).isoformat(),
                }
                for i in range(49)
            ]).to_csv(folder / "snapshots_long.csv", index=False)

            payload = fleet_collection_health(
                snapshots_root=root,
                live=True,
                as_of=datetime(2026, 6, 7, 19, 0),
            )

        self.assertEqual(payload["summary"]["market_count"], 12)
        by_market = {row["market_id"]: row for row in payload["markets"]}
        self.assertEqual(by_market["toronto"]["state"], "CLEAN")
        self.assertEqual(by_market["nyc"]["state"], "MISSING")

    def test_artifact_metadata_records_schema_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.json"
            path.write_text(
                json.dumps({"schema_version": "demo_v1", "generated_at_utc": "2026-06-12T00:00:00Z"}),
                encoding="utf-8",
            )

            meta = artifact_metadata(path, kind="demo")

        self.assertTrue(meta["exists"])
        self.assertEqual(meta["schema_version"], "demo_v1")
        self.assertEqual(meta["schema_status"], "ok")
        self.assertIsNotNone(meta["sha256"])

    def test_overall_status_uses_highest_alert_severity(self):
        self.assertEqual(overall_status([]), "OK")
        self.assertEqual(overall_status([{"severity": "warning"}]), "WARN")
        self.assertEqual(overall_status([{"severity": "warning"}, {"severity": "critical"}]), "CRITICAL")

    def test_trust_readiness_reports_gate_gaps(self):
        rows = trust_readiness([{"market": "nyc", "trust_score": 15, "settled_days": 1}])

        self.assertEqual(rows["nyc"]["trust_gap"], 10)
        self.assertEqual(rows["nyc"]["settled_day_gap"], 1)


if __name__ == "__main__":
    unittest.main()
