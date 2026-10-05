"""Toronto CYYZ/CYTZ NBM block retention: default off, storage only."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from weather.collection.snapshot_store import SnapshotStore
from weather.model.toronto_model import TorontoHighTempModel
from weather.paths import config_path
from weather.sources.toronto_nbm_blocks import (
    POLICY_SCHEMA_VERSION,
    TORONTO_NBM_BLOCKS_SOURCE,
    TorontoNbmBlocksPolicy,
    load_toronto_nbm_blocks_policy,
    toronto_nbm_blocks_enabled,
)


BULLETIN = """
 KLGA    NBM V5.0 NBP GUIDANCE    5/30/2026  0000 UTC
UTC    00  12| 00  12
FHR    24  36| 48  60
TXNMN  84  68| 79  68
TXNSD   2   2|  4   3
TXNP1  81  64| 73  63
TXNP2  82  66| 76  66
TXNP5  84  68| 80  69
TXNP7  85  69| 82  71
TXNP9  86  70| 84  72
 CYYZ    NBM V5.0 NBP GUIDANCE    5/30/2026  0000 UTC
UTC    00  12| 00  12
FHR    24  36| 48  60
TXNMN  24  12| 22  11
TXNSD   2   2|  2   2
TXNP1  21  10| 19   9
TXNP2  22  11| 20  10
TXNP5  24  12| 22  11
TXNP7  25  13| 23  12
TXNP9  27  14| 25  13
 CYTZ    NBM V5.0 NBP GUIDANCE    5/30/2026  0000 UTC
UTC    00  12| 00  12
FHR    24  36| 48  60
TXNMN  22  13| 21  12
TXNSD   2   2|  2   2
TXNP1  19  11| 18  10
TXNP2  20  12| 19  11
TXNP5  22  13| 21  12
TXNP7  23  14| 22  13
TXNP9  24  15| 23  14
"""
CYCLE = datetime(2026, 5, 30, 0, tzinfo=timezone.utc)
ON = TorontoNbmBlocksPolicy(retain_toronto_nbm_blocks=True, status="configured")
OFF = TorontoNbmBlocksPolicy()


def _patch_policy(policy):
    return (
        patch("weather.sources.toronto_nbm_blocks.load_toronto_nbm_blocks_policy", return_value=policy),
        patch("weather.model.model_sources.load_toronto_nbm_blocks_policy", return_value=policy),
    )


def _requested_sources(model):
    calls = []

    def fake_fetch_source_group(fetchers, max_workers=None):
        calls.append(tuple(fetchers))
        return {}

    model.fetch_source_group = fake_fetch_source_group
    model.blend_with_last_good = lambda sources: sources
    model.fetch_live_sources()
    return sorted(name for call in calls for name in call)


def _wu_row(time, temp):
    return {
        "time": time, "datetime": f"2026-05-30T{time}:00-04:00", "temp_c": temp,
        "dewpoint_c": 10.0, "humidity": 60.0, "pressure": 1015.0,
        "clouds": "Partly Cloudy", "condition": "Partly Cloudy",
        "wind": "SW", "wind_kmh": 15.0, "gust_kmh": None,
    }


class TestTorontoNbmBlocksPolicy(unittest.TestCase):
    def test_checked_in_policy_is_off(self):
        policy = load_toronto_nbm_blocks_policy(config_path("toronto_nbm_blocks.json"))
        self.assertEqual(policy.status, "configured")
        self.assertFalse(policy.retain_toronto_nbm_blocks)
        self.assertEqual(policy.stations, ("CYYZ", "CYTZ"))

    def test_missing_or_invalid_policy_fails_safe_to_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.json"
            self.assertFalse(load_toronto_nbm_blocks_policy(path).retain_toronto_nbm_blocks)
            for raw in (
                "not json",
                json.dumps({"schema_version": "other", "capture": {"retain_toronto_nbm_blocks": True}}),
                json.dumps({"schema_version": POLICY_SCHEMA_VERSION, "capture": {"retain_toronto_nbm_blocks": "yes"}}),
                json.dumps({"schema_version": POLICY_SCHEMA_VERSION, "capture": {"retain_toronto_nbm_blocks": True, "stations": []}}),
            ):
                path.write_text(raw, encoding="utf-8")
                policy = load_toronto_nbm_blocks_policy(path)
                self.assertFalse(policy.retain_toronto_nbm_blocks, raw)
                self.assertTrue(policy.status.startswith("invalid_fail_safe"), raw)

    def test_enabled_policy_applies_to_toronto_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.json"
            path.write_text(json.dumps({
                "schema_version": POLICY_SCHEMA_VERSION,
                "capture": {"retain_toronto_nbm_blocks": True, "stations": ["cyyz", "CYTZ", "CYYZ"]},
            }), encoding="utf-8")
            policy = load_toronto_nbm_blocks_policy(path)
        self.assertTrue(policy.retain_toronto_nbm_blocks)
        self.assertEqual(policy.stations, ("CYYZ", "CYTZ"))
        toronto = TorontoHighTempModel(target_date="2026-05-30", market_id="toronto").spec
        nyc = TorontoHighTempModel(target_date="2026-05-30", market_id="nyc").spec
        self.assertTrue(toronto_nbm_blocks_enabled(toronto, policy))
        self.assertFalse(toronto_nbm_blocks_enabled(nyc, policy))
        self.assertFalse(toronto_nbm_blocks_enabled(toronto, OFF))


class TestTorontoNbmBlocksCapture(unittest.TestCase):
    def test_flag_off_keeps_todays_toronto_source_set(self):
        a, b = _patch_policy(OFF)
        with a, b:
            names = _requested_sources(TorontoHighTempModel(target_date="2026-05-30", market_id="toronto"))
        self.assertNotIn(TORONTO_NBM_BLOCKS_SOURCE, names)
        self.assertNotIn("nbm_probabilistic_tmax", names)

    def test_flag_on_adds_only_the_capture_source_for_toronto(self):
        a, b = _patch_policy(OFF)
        with a, b:
            off = _requested_sources(TorontoHighTempModel(target_date="2026-05-30", market_id="toronto"))
            nyc_off = _requested_sources(TorontoHighTempModel(target_date="2026-05-30", market_id="nyc"))
        a, b = _patch_policy(ON)
        with a, b:
            on = _requested_sources(TorontoHighTempModel(target_date="2026-05-30", market_id="toronto"))
            nyc_on = _requested_sources(TorontoHighTempModel(target_date="2026-05-30", market_id="nyc"))
        self.assertEqual(sorted(set(on) - set(off)), [TORONTO_NBM_BLOCKS_SOURCE])
        self.assertNotIn("nbm_probabilistic_tmax", on)
        self.assertEqual(nyc_on, nyc_off)

    def test_flag_on_retains_cyyz_and_cytz_blocks_without_national_text(self):
        model = TorontoHighTempModel(target_date="2026-05-30", market_id="toronto")
        model.cached_source_for_reuse = lambda *args, **kwargs: None
        seen = []
        model.get_text = lambda url: seen.append(url) or BULLETIN
        a, b = _patch_policy(ON)
        with a, b, patch("weather.model.model_sources.nbp_cycle_candidates", return_value=[CYCLE]):
            payload = model.fetch_nbm_toronto_station_blocks()

        self.assertEqual(len(seen), 1)
        self.assertTrue(payload["available"])
        self.assertFalse(payload["feeds_features"])
        self.assertEqual(payload["stations_found"], ["CYYZ", "CYTZ"])
        self.assertEqual(payload["stations"]["CYYZ"]["percentiles"]["50"], 24.0)
        self.assertEqual(payload["stations"]["CYTZ"]["percentiles"]["90"], 24.0)
        blocks = payload["raw_payload"]["station_blocks"]
        self.assertTrue(blocks["CYYZ"].lstrip().startswith("CYYZ    NBM"))
        self.assertTrue(blocks["CYTZ"].lstrip().startswith("CYTZ    NBM"))
        self.assertNotIn("KLGA", json.dumps(payload))
        self.assertEqual(payload["national_bulletin"]["cycle_key"], "nbm-nbp:20260530T00Z")
        self.assertNotIn("forecast_payload_attestation", payload["raw_payload"])

    def test_missing_station_is_stored_as_missing_without_walking_older_bulletins(self):
        model = TorontoHighTempModel(target_date="2026-05-30", market_id="toronto")
        model.cached_source_for_reuse = lambda *args, **kwargs: None
        seen = []
        us_only = BULLETIN.split(" CYYZ")[0]
        model.get_text = lambda url: seen.append(url) or us_only
        older = datetime(2026, 5, 29, 23, tzinfo=timezone.utc)
        a, b = _patch_policy(ON)
        with a, b, patch("weather.model.model_sources.nbp_cycle_candidates", return_value=[CYCLE, older]):
            payload = model.fetch_nbm_toronto_station_blocks()
        self.assertEqual(len(seen), 1)
        self.assertFalse(payload["available"])
        self.assertEqual(payload["stations_found"], [])

    def test_retained_blocks_do_not_change_toronto_features(self):
        model = TorontoHighTempModel(target_date="2026-05-30", market_id="toronto")
        model.cached_source_for_reuse = lambda *args, **kwargs: None
        model.get_text = lambda url: BULLETIN
        a, b = _patch_policy(ON)
        with a, b, patch("weather.model.model_sources.nbp_cycle_candidates", return_value=[CYCLE]):
            retained = model.fetch_nbm_toronto_station_blocks()
        rows = [_wu_row("07:00", 18.0), _wu_row("12:00", 22.0)]
        base = {
            "wu_history": {"ok": True, "data": {"rows": rows}},
            "wu_current": {"ok": True, "data": {"temp_c": 22.0}},
            "open_meteo": {"ok": True, "data": {"rows": [], "day_max_c": 25.0}},
            "eccc_citypage": {"ok": True, "data": {"forecast_high_c": 27.0}},
        }
        with_blocks = dict(base)
        with_blocks[TORONTO_NBM_BLOCKS_SOURCE] = {"ok": True, "status": "fresh", "data": retained}

        before = model.extract_live_features(base, cutoff_hour=12)
        after = model.extract_live_features(with_blocks, cutoff_hour=12)

        self.assertEqual(json.dumps(before, sort_keys=True, default=str), json.dumps(after, sort_keys=True, default=str))
        for percentile in (10, 25, 50, 75, 90):
            self.assertIsNone(after.get(f"nbm_prob_tmax_p{percentile}"))

    def test_retained_blocks_persist_as_small_local_forecast_payload(self):
        model = TorontoHighTempModel(target_date="2026-05-30", market_id="toronto")
        model.cached_source_for_reuse = lambda *args, **kwargs: None
        model.get_text = lambda url: BULLETIN
        a, b = _patch_policy(ON)
        with a, b, patch("weather.model.model_sources.nbp_cycle_candidates", return_value=[CYCLE]):
            retained = model.fetch_nbm_toronto_station_blocks()
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(root=tmp, event_slug="event")
            rows = store.write_forecast_payloads(
                {TORONTO_NBM_BLOCKS_SOURCE: {
                    "ok": True,
                    "status": "fresh",
                    "fetched_at": "2026-05-30T01:00:00+00:00",
                    "data": retained,
                }},
                "snap-1",
                datetime(2026, 5, 30, 1, tzinfo=timezone.utc),
                "model-v",
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], TORONTO_NBM_BLOCKS_SOURCE)
        self.assertLess(int(rows[0]["payload_bytes"]), 4096)


if __name__ == "__main__":
    unittest.main()
