import unittest
from datetime import date

from weather.sources.nbm_probabilistic_tmax import (
    exceedance_probability_from_percentiles,
    nbp_text_url,
    parse_nbp_station_tmax,
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


def payload_datetime(value):
    from datetime import datetime

    return datetime.fromisoformat(value)


if __name__ == "__main__":
    unittest.main()
