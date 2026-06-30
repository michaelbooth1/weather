import unittest
import tempfile
from datetime import datetime, timezone

from weather.collection.snapshot_store import SnapshotStore


class TestForecastPayloadPersistence(unittest.TestCase):
    def test_forecast_payload_manifest_accepts_source_url_without_storing_raw_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(root=tmp, event_slug="event")
            rows = store.write_forecast_payloads(
                {
                    "nbm_probabilistic_tmax": {
                        "ok": True,
                        "status": "fresh",
                        "fetched_at": "2026-06-15T16:00:00+00:00",
                        "data": {
                            "source_url": "https://example.test/blend_nbptx.t00z",
                            "issued_at": "2026-06-15T12:00:00+00:00",
                            "valid_time_utc": "2026-06-16T12:00:00+00:00",
                            "raw_payload": {
                                "source_kind": "nbp_station_text",
                                "station_id": "KLGA",
                                "text": "KLGA NBM V5.0 NBP GUIDANCE",
                            },
                        },
                    }
                },
                "snap-1",
                datetime(2026, 6, 15, 16, 0, tzinfo=timezone.utc),
                "model-v",
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "nbm_probabilistic_tmax")
        self.assertEqual(rows[0]["source_url"], "https://example.test/blend_nbptx.t00z")
        self.assertEqual(rows[0]["provider_issue_time"], "2026-06-15T12:00:00+00:00")
        self.assertEqual(rows[0]["provider_update_time"], "2026-06-16T12:00:00+00:00")
        self.assertTrue(rows[0]["payload_hash"])
        self.assertGreater(rows[0]["payload_bytes"], 0)
        self.assertEqual(rows[0]["raw_payload_path"], "")


if __name__ == "__main__":
    unittest.main()
