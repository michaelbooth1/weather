import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.research.reanalysis_synoptic_band_ablation import (
    build_ablation_payload,
    merge_source_family_ablation,
    paired_ablation_rows,
)


def _row(snapshot_id, distance, base_p, *, market_id="atlanta", outcome=1):
    return {
        "market_id": market_id,
        "snapshot_id": snapshot_id,
        "target_date": "2026-06-07",
        "bin_type": "eq",
        "bin_value": "84",
        "bin_value_hi": "84",
        "candidate_cutoff_hour": 8,
        "candidate_cutoff_regime": "early",
        "settlement_distance_bucket": distance,
        "candidate_p": base_p,
        "market_yes": 0.40,
        "outcome": outcome,
    }


class TestReanalysisSynopticBandAblation(unittest.TestCase):
    def test_pairs_full_and_masked_artifact_rows_for_source_family_payload(self):
        base = [
            _row("s1", "0", 0.70, outcome=1),
            _row("s2", "1", 0.20, outcome=0),
            _row("s3", "3+", 0.10, outcome=0, market_id="toronto"),
        ]
        masked = [
            _row("s1", "0", 0.55, outcome=1),
            _row("s2", "1", 0.30, outcome=0),
            _row("s3", "3+", 0.25, outcome=0, market_id="toronto"),
        ]

        rows = paired_ablation_rows(base, masked)
        payload = build_ablation_payload(rows, artifact_path="candidate.pkl", artifact_hash="abc")

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["settlement_distance"], "exact")
        self.assertEqual(rows[1]["settlement_distance"], "adjacent")
        self.assertEqual(rows[2]["settlement_distance"], "far")
        [variant] = payload["variants"]
        self.assertEqual(variant["variant"], "reanalysis_synoptic")
        self.assertEqual(variant["evidence_source"], "candidate_artifact_band_ablation")
        self.assertTrue(any(row["slice"] == "settlement_distance" for row in payload["slice_effects"]))

    def test_merge_source_family_ablation_replaces_existing_reanalysis_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source_family_ablation.json"
            base_payload = {
                "schema_version": "source_family_ablation_v0.1",
                "requested_variants": ["open_meteo", "reanalysis_synoptic"],
                "summary": {"variant_count": 2, "rows_scored": 20, "slice_effect_count": 2},
                "variants": [
                    {"variant": "open_meteo", "n": 10},
                    {"variant": "reanalysis_synoptic", "n": 10, "delta": -0.1},
                ],
                "day_effects": {
                    "open_meteo": [{"day": "atlanta 2026-06-07", "delta": 0.1}],
                    "reanalysis_synoptic": [{"day": "old", "delta": -0.1}],
                },
                "slice_effects": [
                    {"variant": "open_meteo", "slice": "market"},
                    {"variant": "reanalysis_synoptic", "slice": "market", "delta": -0.1},
                ],
            }
            supplemental = {
                "requested_variants": ["reanalysis_synoptic"],
                "variants": [{"variant": "reanalysis_synoptic", "n": 30, "delta": 0.2}],
                "day_effects": {"reanalysis_synoptic": [{"day": "new", "delta": 0.2}]},
                "slice_effects": [
                    {"variant": "reanalysis_synoptic", "slice": "settlement_distance", "delta": 0.2}
                ],
            }
            path.write_text(json.dumps(base_payload), encoding="utf-8")

            merged = merge_source_family_ablation(base_payload, supplemental)

        variants = {row["variant"]: row for row in merged["variants"]}
        self.assertEqual(variants["open_meteo"]["n"], 10)
        self.assertEqual(variants["reanalysis_synoptic"]["n"], 30)
        self.assertEqual(merged["day_effects"]["reanalysis_synoptic"][0]["day"], "new")
        self.assertEqual(len([row for row in merged["slice_effects"] if row["variant"] == "reanalysis_synoptic"]), 1)
        self.assertEqual(merged["summary"]["variant_count"], 2)
        self.assertEqual(merged["summary"]["rows_scored"], 40)


if __name__ == "__main__":
    unittest.main()
