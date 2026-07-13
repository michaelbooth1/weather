import unittest
import tempfile
import hashlib
import os
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

from weather.collection.snapshot_store import (
    FORECAST_RAW_PAYLOAD_RETENTION_ENV,
    OBSERVATION_RAW_PAYLOAD_RETENTION_ENV,
    SnapshotStore,
)
from weather.model.model_sources import SOURCE_PAYLOAD_CONTRACTS, SourceFetchMixin
from weather.model.source_adapters import fetch_source_group


class TestForecastPayloadPersistence(unittest.TestCase):
    def test_retained_payloads_serialize_once_and_stream_existing_blob_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(root=tmp, event_slug="event")
            forecast_sources = {
                "nws_grid": {"data": {"raw_payload": {"text": "x" * 4096}}}
            }
            observation_sources = {
                "metar": {"data": {"raw_payload": {"text": "METAR KLGA"}}}
            }
            original = store.canonical_raw_payload
            with patch.object(store, "canonical_raw_payload", wraps=original) as serializer:
                first = store.write_forecast_payloads(
                    forecast_sources,
                    "f1",
                    datetime(2026, 7, 12, 11, tzinfo=timezone.utc),
                    "model-v",
                )[0]
                self.assertEqual(serializer.call_count, 1)

            # The dedupe validation must not load the existing blob at once.
            with patch.object(Path, "read_bytes", side_effect=AssertionError("unbounded read")):
                second = store.write_forecast_payloads(
                    forecast_sources,
                    "f2",
                    datetime(2026, 7, 12, 11, 10, tzinfo=timezone.utc),
                    "model-v",
                )[0]
            self.assertEqual(first["payload_hash"], second["payload_hash"])
            self.assertFalse(second["payload_blob_created"])

            with patch.object(store, "canonical_raw_payload", wraps=original) as serializer:
                store.write_observation_payloads(
                    observation_sources,
                    "o1",
                    datetime(2026, 7, 12, 11, tzinfo=timezone.utc),
                    "model-v",
                )
                self.assertEqual(serializer.call_count, 1)

    def test_source_adapter_attempt_and_parser_contract_reach_snapshot_manifest(self):
        class StubSourceModel(SourceFetchMixin):
            pass

        source_model = StubSourceModel()
        fetcher = source_model.source_fetcher_with_contract(
            "nws_grid",
            lambda: {
                "provider_issue_time": "2026-07-12T10:00:00+00:00",
                "raw_payload": {"temperature": [82, 83]},
            },
        )
        timestamps = iter(
            [
                datetime(2026, 7, 12, 10, 59, 58, tzinfo=timezone.utc),
                datetime(2026, 7, 12, 11, 0, 2, tzinfo=timezone.utc),
            ]
        )
        sources = fetch_source_group(
            {"nws_grid": fetcher},
            timezone=timezone.utc,
            now_fn=lambda: next(timestamps),
            max_workers=1,
        )

        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(root=tmp, event_slug="event")
            row = store.write_forecast_payloads(
                sources,
                "s1",
                datetime(2026, 7, 12, 11, 1, tzinfo=timezone.utc),
                "model-v",
            )[0]

        parser_version, payload_schema_version = SOURCE_PAYLOAD_CONTRACTS["nws_grid"]
        self.assertEqual(row["request_started_at"], "2026-07-12T10:59:58+00:00")
        self.assertEqual(row["response_received_at"], "2026-07-12T11:00:02+00:00")
        self.assertEqual(row["fetched_at"], "2026-07-12T11:00:02+00:00")
        self.assertEqual(row["parser_version"], parser_version)
        self.assertEqual(row["payload_schema_version"], payload_schema_version)

    def test_forecast_payload_manifest_retains_sha256_content_addressed_body_by_default(self):
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
            raw_path = Path(rows[0]["raw_payload_path"])
            raw_bytes = raw_path.read_bytes().removesuffix(b"\n")

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source"], "nbm_probabilistic_tmax")
            self.assertEqual(rows[0]["source_url"], "https://example.test/blend_nbptx.t00z")
            self.assertEqual(rows[0]["provider_issue_time"], "2026-06-15T12:00:00+00:00")
            self.assertEqual(rows[0]["provider_update_time"], "2026-06-16T12:00:00+00:00")
            self.assertEqual(rows[0]["payload_hash_algorithm"], "sha256-canonical-json")
            self.assertEqual(rows[0]["payload_hash"], hashlib.sha256(raw_bytes).hexdigest())
            self.assertEqual(raw_path.name, f'{rows[0]["payload_hash"]}.json')
            self.assertTrue(rows[0]["raw_payload_retained"])
            self.assertTrue(rows[0]["payload_blob_created"])

    def test_repeated_forecast_payload_deduplicates_blob_and_preserves_first_seen(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(root=tmp, event_slug="event")
            source = {
                "nws_grid": {
                    "ok": True,
                    "request_started_at": "2026-07-12T10:59:58+00:00",
                    "fetched_at": "2026-07-12T11:00:00+00:00",
                    "data": {
                        "provider_issue_time": "2026-07-12T10:00:00+00:00",
                        "forecast_run_time": "2026-07-12T06:00:00+00:00",
                        "grid_id": "OKX/33,37",
                        "parser_version": "nws-grid-v3",
                        "payload_schema_version": "nws-api-v1",
                        "raw_payload": {"temperature": [82, 83]},
                    },
                }
            }
            first = store.write_forecast_payloads(
                source,
                "s1",
                datetime(2026, 7, 12, 11, tzinfo=timezone.utc),
                "model-v",
                runtime_identity={"schema_version": "runtime-v1", "git_commit": "abc"},
                release_lineage={"release_id": "release-1", "release_identity_status": "verified"},
                model_identity={"identity_hash": "model-hash"},
                config_identity={"market_id": "nyc"},
            )[0]
            second = store.write_forecast_payloads(
                source,
                "s2",
                datetime(2026, 7, 12, 11, 10, tzinfo=timezone.utc),
                "model-v",
            )[0]

            self.assertEqual(first["raw_payload_path"], second["raw_payload_path"])
            self.assertTrue(first["payload_blob_created"])
            self.assertFalse(second["payload_blob_created"])
            self.assertEqual(first["first_seen_at"], second["first_seen_at"])
            self.assertEqual(first["request_started_at"], "2026-07-12T10:59:58+00:00")
            self.assertEqual(first["response_received_at"], "2026-07-12T11:00:00+00:00")
            self.assertEqual(first["forecast_run_time"], "2026-07-12T06:00:00+00:00")
            self.assertEqual(first["grid_id"], "OKX/33,37")
            self.assertEqual(first["release_id"], "release-1")
            self.assertEqual(first["model_identity_hash"], "model-hash")

    def test_observation_payload_uses_its_own_content_addressed_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(root=tmp, event_slug="event")
            sources = {
                "metar": {
                    "fetched_at": "2026-07-12T11:00:02+00:00",
                    "data": {
                        "provider_observed_at": "2026-07-12T10:55:00+00:00",
                        "station_id": "KLGA",
                        "parser_version": "metar-v2",
                        "payload_schema_version": "metar-text-v1",
                        "raw_payload": {"raw": "METAR KLGA 121055Z"},
                    },
                }
            }
            observation = store.write_observation_payloads(
                sources,
                "s1",
                datetime(2026, 7, 12, 11, 1, tzinfo=timezone.utc),
                "model-v",
            )[0]
            forecast = store.write_forecast_payloads(
                sources,
                "s1",
                datetime(2026, 7, 12, 11, 1, tzinfo=timezone.utc),
                "model-v",
            )

            raw_path = Path(observation["raw_payload_path"])
            self.assertEqual(observation["schema_version"], "observation_payload_manifest_v1")
            self.assertEqual(raw_path.parent.parent.name, "sha256")
            self.assertEqual(raw_path.name, f'{observation["payload_hash"]}.json')
            self.assertEqual(observation["provider_station_id"], "KLGA")
            self.assertEqual(forecast, [])
            self.assertFalse((Path(tmp) / "forecast_payloads").exists())

    def test_explicit_opt_out_keeps_manifest_without_raw_forecast_or_observation_blob(self):
        old_forecast = os.environ.get(FORECAST_RAW_PAYLOAD_RETENTION_ENV)
        old_observation = os.environ.get(OBSERVATION_RAW_PAYLOAD_RETENTION_ENV)
        try:
            os.environ[FORECAST_RAW_PAYLOAD_RETENTION_ENV] = "off"
            os.environ[OBSERVATION_RAW_PAYLOAD_RETENTION_ENV] = "false"
            with tempfile.TemporaryDirectory() as tmp:
                store = SnapshotStore(root=tmp, event_slug="event")
                forecast = store.write_forecast_payloads(
                    {"nws_grid": {"data": {"raw_payload": {"x": 1}}}},
                    "s1",
                    datetime(2026, 7, 12, 11, tzinfo=timezone.utc),
                    "model-v",
                )[0]
                observation = store.write_observation_payloads(
                    {"metar": {"data": {"raw_payload": {"temp": 21}}}},
                    "s1",
                    datetime(2026, 7, 12, 11, tzinfo=timezone.utc),
                    "model-v",
                )[0]
                self.assertEqual(forecast["raw_payload_path"], "")
                self.assertEqual(observation["raw_payload_path"], "")
                self.assertFalse(forecast["raw_payload_retained"])
                self.assertFalse(observation["raw_payload_retained"])
                self.assertFalse((Path(tmp) / "forecast_payloads").exists())
                self.assertFalse((Path(tmp) / "observation_payloads").exists())
        finally:
            if old_forecast is None:
                os.environ.pop(FORECAST_RAW_PAYLOAD_RETENTION_ENV, None)
            else:
                os.environ[FORECAST_RAW_PAYLOAD_RETENTION_ENV] = old_forecast
            if old_observation is None:
                os.environ.pop(OBSERVATION_RAW_PAYLOAD_RETENTION_ENV, None)
            else:
                os.environ[OBSERVATION_RAW_PAYLOAD_RETENTION_ENV] = old_observation


if __name__ == "__main__":
    unittest.main()
