import unittest
import csv
import json
import tempfile
from datetime import date
from pathlib import Path

from weather.sources.nbm_probabilistic_tmax import (
    NBPStationArchiveStore,
    exceedance_probability_from_percentiles,
    extract_qmd_grib_tmax_point,
    nbp_station_archive_summary,
    nbp_station_archive_row,
    nbp_text_url,
    parse_nbp_station_tmax,
    qmd_grib_idx_url,
    qmd_grib_url,
    replay_nbp_station_archive_row,
    select_qmd_tmax_idx_records,
    station_nbp_block,
)


NBP_TEXT = """
 KBOS    NBM V5.0 NBP GUIDANCE    5/30/2026  0000 UTC
FHR    24  36| 48  60
TXNP5  70  58| 73  62

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

 KJFK    NBM V5.0 NBP GUIDANCE    5/30/2026  0000 UTC
FHR    24  36| 48  60
TXNP5  79  66| 82  70
"""

QMD_IDX_TEXT = (
    "1:0:d=2026053000:TMAX:2 m above ground:24 hour fcst:10% level:\n"
    "2:100:d=2026053000:TMAX:2 m above ground:24 hour fcst:25% level:\n"
    "3:200:d=2026053000:TMAX:2 m above ground:24 hour fcst:50% level:\n"
    "4:300:d=2026053000:TMAX:2 m above ground:24 hour fcst:75% level:\n"
    "5:400:d=2026053000:TMAX:2 m above ground:24 hour fcst:90% level:\n"
    "6:500:d=2026053000:TMAX:2 m above ground:24 hour fcst:prob > 90:\n"
    "7:600:d=2026053000:TMP:2 m above ground:24 hour fcst:50% level:\n"
)


class TestNbmProbabilisticTmax(unittest.TestCase):
    def test_station_block_stops_at_next_station_header(self):
        block = station_nbp_block(NBP_TEXT, "KLGA")

        self.assertTrue(block[0].strip().startswith("KLGA"))
        self.assertIn("TXNP9", "\n".join(block))
        self.assertNotIn("KJFK", "\n".join(block))

    def test_parse_station_tmax_percentiles_for_target_day(self):
        payload = parse_nbp_station_tmax(
            NBP_TEXT,
            "KLGA",
            date(2026, 5, 30),
            source_url="https://example.test/blend_nbptx.t00z",
            fetched_at="2026-05-30T01:00:00+00:00",
        )

        self.assertTrue(payload["available"])
        self.assertEqual(payload["station_id"], "KLGA")
        self.assertEqual(payload["issued_at"], "2026-05-30T00:00:00+00:00")
        self.assertEqual(payload["forecast_hour"], 24)
        self.assertEqual(payload["percentiles"]["10"], 81.0)
        self.assertEqual(payload["percentiles"]["25"], 82.0)
        self.assertEqual(payload["percentiles"]["50"], 84.0)
        self.assertEqual(payload["percentiles"]["75"], 85.0)
        self.assertEqual(payload["percentiles"]["90"], 86.0)
        self.assertEqual(payload["mean_native"], 84.0)
        self.assertEqual(payload["stddev_native"], 2.0)
        self.assertEqual(payload["day_max_native"], 84.0)
        self.assertEqual(payload["p10_p90_spread"], 5.0)
        self.assertEqual(payload["iqr"], 3.0)
        self.assertFalse(payload["historical_archive_available"])
        self.assertEqual(payload["exceedance_status"], "native_qmd_grid_or_band_edge_extraction_pending")
        self.assertEqual(len(payload["payload_hash"]), 40)
        self.assertEqual(payload["url"], "https://example.test/blend_nbptx.t00z")
        self.assertEqual(payload["raw_payload"]["source_kind"], "nbp_station_text")
        self.assertIn("KLGA", payload["raw_payload"]["text"])

    def test_station_archive_row_and_store_preserve_payload_provenance(self):
        payload = parse_nbp_station_tmax(
            NBP_TEXT,
            "KLGA",
            date(2026, 5, 30),
            source_url="https://example.test/blend_nbptx.t00z",
            fetched_at="2026-05-30T01:00:00+00:00",
        )

        with tempfile.TemporaryDirectory() as tmp:
            store = NBPStationArchiveStore(tmp)
            first = store.write_payload(payload)
            second = store.write_payload(payload)
            rows = list(csv.DictReader(Path(first["rows_path"]).open(encoding="utf-8", newline="")))
            raw_payload = json.loads(Path(first["raw_payload_path"]).read_text(encoding="utf-8"))

        archive_row = nbp_station_archive_row(payload, raw_payload_path="payload.json")
        self.assertEqual(archive_row["schema_version"], "nbm_probabilistic_tmax_station_archive_v0.1")
        self.assertEqual(archive_row["p90"], 86.0)
        self.assertEqual(first["written_row_count"], 1)
        self.assertEqual(second["written_row_count"], 0)
        self.assertEqual(second["skipped_existing_row_count"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["station_id"], "KLGA")
        self.assertEqual(rows[0]["source_url"], "https://example.test/blend_nbptx.t00z")
        self.assertEqual(raw_payload["station_id"], "KLGA")
        self.assertIn("TXNP9", raw_payload["text"])

    def test_station_archive_replays_from_raw_payload(self):
        payload = parse_nbp_station_tmax(
            NBP_TEXT,
            "KLGA",
            date(2026, 5, 30),
            source_url="https://example.test/blend_nbptx.t00z",
            fetched_at="2026-05-30T01:00:00+00:00",
        )

        with tempfile.TemporaryDirectory() as tmp:
            store = NBPStationArchiveStore(tmp)
            first = store.write_payload(payload)
            rows = list(csv.DictReader(Path(first["rows_path"]).open(encoding="utf-8", newline="")))
            replay = replay_nbp_station_archive_row(rows[0], rows_path=first["rows_path"])
            summary = nbp_station_archive_summary(tmp)

        self.assertEqual(replay["status"], "PASS")
        self.assertTrue(replay["replay_safe"])
        self.assertEqual(replay["replayed_percentiles"]["90"], 86.0)
        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["replay_safe_row_count"], 1)

    def test_station_archive_replay_detects_payload_drift(self):
        payload = parse_nbp_station_tmax(
            NBP_TEXT,
            "KLGA",
            date(2026, 5, 30),
            source_url="https://example.test/blend_nbptx.t00z",
            fetched_at="2026-05-30T01:00:00+00:00",
        )

        with tempfile.TemporaryDirectory() as tmp:
            store = NBPStationArchiveStore(tmp)
            first = store.write_payload(payload)
            raw_path = Path(first["raw_payload_path"])
            raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
            raw_payload["text"] = raw_payload["text"].replace("TXNP9  86  70", "TXNP9  87  70")
            raw_path.write_text(json.dumps(raw_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            summary = nbp_station_archive_summary(tmp)

        self.assertEqual(summary["status"], "FAIL")
        self.assertEqual(summary["failed_row_count"], 1)
        self.assertIn("raw_payload_hash_mismatch", summary["failed_samples"][0]["issues"])
        self.assertIn("p90_mismatch", summary["failed_samples"][0]["issues"])

    def test_missing_station_returns_unavailable_payload(self):
        payload = parse_nbp_station_tmax(NBP_TEXT, "KATL", "2026-05-30")

        self.assertFalse(payload["available"])
        self.assertEqual(payload["reason"], "station_not_found_in_nbp_text")
        self.assertEqual(payload["station_id"], "KATL")

    def test_exceedance_interpolates_across_percentile_curve(self):
        percentiles = {"10": 81, "25": 82, "50": 84, "75": 85, "90": 86}

        self.assertEqual(exceedance_probability_from_percentiles(percentiles, 85), 0.25)
        self.assertAlmostEqual(exceedance_probability_from_percentiles(percentiles, 84.5), 0.375)
        self.assertAlmostEqual(exceedance_probability_from_percentiles(percentiles, 86), 0.10)

    def test_nbp_text_url_uses_blend_cycle_layout(self):
        payload = parse_nbp_station_tmax(NBP_TEXT, "KLGA", date(2026, 5, 31))

        self.assertTrue(payload["available"])
        self.assertEqual(payload["forecast_hour"], 48)
        self.assertEqual(nbp_text_url(payload_datetime("2026-05-30T00:00:00+00:00")), "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/blend.20260530/00/text/blend_nbptx.t00z")

    def test_qmd_grib_url_uses_operational_blend_layout(self):
        url = qmd_grib_url(payload_datetime("2026-05-30T00:00:00+00:00"), 24, domain="co")

        self.assertEqual(
            url,
            "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/"
            "blend.20260530/00/qmd/blend.t00z.qmd.f024.co.grib2",
        )
        self.assertEqual(qmd_grib_idx_url(url), url + ".idx")

    def test_qmd_idx_selection_finds_tmax_percentile_and_exceedance_records(self):
        selected = select_qmd_tmax_idx_records(
            QMD_IDX_TEXT,
            percentiles=(10, 50, 90),
            exceedance_thresholds=(90,),
        )

        by_kind = {(row["kind"], row.get("percentile"), row.get("threshold")) for row in selected}
        self.assertIn(("percentile", 10, None), by_kind)
        self.assertIn(("percentile", 50, None), by_kind)
        self.assertIn(("percentile", 90, None), by_kind)
        self.assertIn(("exceedance_probability", None, 90.0), by_kind)
        self.assertFalse(any(":TMP:" in row["match"] for row in selected))
        self.assertTrue(any("10% level" in row["match"] for row in selected))

    def test_qmd_grib_point_extraction_converts_kelvin_percentiles(self):
        values_by_match = {
            "10% level": 299.8166667,
            "25% level": 300.3722222,
            "50% level": 300.9277778,
            "75% level": 301.4833333,
            "90% level": 302.0388889,
            "prob > 90": 35.0,
        }
        captured_matches = []

        def fake_extractor(grib_path, *, lon, lat, match, wgrib2_path=None):
            captured_matches.append(match)
            for token, value in values_by_match.items():
                if token in match:
                    return {
                        "value": value,
                        "lon": lon,
                        "lat": lat,
                        "match": match,
                        "command": ["fake-wgrib2"],
                    }
            raise AssertionError(match)

        payload = extract_qmd_grib_tmax_point(
            "blend.t00z.qmd.f024.co.grib2",
            QMD_IDX_TEXT,
            lon=-73.78,
            lat=40.64,
            run_time=payload_datetime("2026-05-30T00:00:00+00:00"),
            forecast_hour=24,
            target_date=date(2026, 5, 30),
            source_url="https://example.test/blend.t00z.qmd.f024.co.grib2",
            percentiles=(10, 25, 50, 75, 90),
            exceedance_thresholds=(90,),
            extractor=fake_extractor,
        )

        self.assertTrue(payload["available"])
        self.assertEqual(payload["source_kind"], "qmd_grib_point")
        self.assertAlmostEqual(payload["percentiles"]["10"], 80.0, places=3)
        self.assertAlmostEqual(payload["percentiles"]["50"], 82.0, places=3)
        self.assertAlmostEqual(payload["percentiles"]["90"], 84.0, places=3)
        self.assertAlmostEqual(payload["p10_p90_spread"], 4.0, places=3)
        self.assertAlmostEqual(payload["iqr"], 2.0, places=3)
        self.assertEqual(payload["exceedance_probabilities"]["90.0"], 0.35)
        self.assertEqual(payload["exceedance_status"], "native_qmd_grib_extracted")
        self.assertGreaterEqual(len(captured_matches), 6)


def payload_datetime(value):
    from datetime import datetime

    return datetime.fromisoformat(value)


if __name__ == "__main__":
    unittest.main()
