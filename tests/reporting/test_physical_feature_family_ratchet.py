import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.physical_feature_family_ratchet import build_ratchet, render_report, write_outputs


def _family_row(
    family_id,
    *,
    lineage="PASS",
    parity="PASS",
    ablation_status="PRESENT",
    delta=0.02,
    active_count=1,
    active_status="ACTIVE_FEATURES",
    live_only=False,
    policy="training_and_serving",
):
    return {
        "family_id": family_id,
        "label": family_id.replace("_", " ").title(),
        "owner": "test",
        "source_keys": [family_id],
        "lineage_artifacts": ["source_status_long.csv", "features_long.csv"],
        "lineage_status": lineage,
        "train_serve_parity_status": parity,
        "historical_archive_status": "test_archive",
        "live_only": live_only,
        "live_only_policy": policy,
        "model_influence": True,
        "configured_model_influence": True,
        "active_model_usage_status": active_status,
        "active_model_feature_count": active_count,
        "active_model_feature_columns": [f"{family_id}_feature"] if active_count else [],
        "missing_required_parity_feature_columns": [],
        "feature_missingness": {"missing_rate": 0.0, "by_market": [], "by_cutoff_hour": []},
        "ablation": {
            "status": ablation_status,
            "variant": family_id,
            "n": 24,
            "days": 2,
            "delta": delta,
            "days_source_helped": 2,
            "days_source_hurt": 0,
        },
    }


def _slice_rows(variant, delta=0.02):
    return [
        {
            "variant": variant,
            "slice": "market",
            "market_id": "atlanta",
            "n": 12,
            "days": 2,
            "base_brier": 0.2,
            "variant_brier": 0.22,
            "delta": delta,
        },
        {
            "variant": variant,
            "slice": "cutoff_regime",
            "cutoff_regime": "early",
            "n": 12,
            "days": 2,
            "base_brier": 0.2,
            "variant_brier": 0.22,
            "delta": delta,
        },
        {
            "variant": variant,
            "slice": "market_cutoff_regime",
            "market_id": "atlanta",
            "cutoff_regime": "early",
            "n": 12,
            "days": 2,
            "base_brier": 0.2,
            "variant_brier": 0.22,
            "delta": delta,
        },
        {
            "variant": variant,
            "slice": "settlement_distance",
            "settlement_distance": "exact",
            "n": 12,
            "days": 2,
            "base_brier": 0.2,
            "variant_brier": 0.22,
            "delta": delta,
        },
    ]


class TestPhysicalFeatureFamilyRatchet(unittest.TestCase):
    def test_builds_strict_family_statuses_and_excludes_clob_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = root / "source_family_inventory.json"
            ablation = root / "source_family_ablation.json"
            inventory.write_text(
                json.dumps(
                    {
                        "schema_version": "source_family_inventory_v0.1",
                        "status": "BLOCK",
                        "inventory": [
                            _family_row("forecast_baseline", delta=0.02),
                            _family_row("open_meteo_expanded", delta=0.02),
                            _family_row("nws_grid", lineage="PARTIAL_SOURCE_STATUS", parity="LINEAGE_BLOCKED", active_count=0),
                            _family_row(
                                "multi_model_guidance",
                                active_count=0,
                                active_status="NOT_USED_BY_ACTIVE_ARTIFACT",
                                live_only=True,
                                policy="live_only_diagnostic_until_backfilled",
                            ),
                            _family_row("mrms_precip", active_count=0, active_status="NOT_USED_BY_ACTIVE_ARTIFACT"),
                            _family_row("marine_context", ablation_status="MISSING", delta=None),
                            _family_row("reanalysis_synoptic", delta=-0.01),
                            _family_row("clob_microstructure", delta=0.03),
                        ],
                    }
                ),
                encoding="utf-8",
            )
            ablation.write_text(
                json.dumps(
                    {
                        "schema_version": "source_family_ablation_v0.1",
                        "slice_effects": _slice_rows("forecast_baseline", 0.02)
                        + _slice_rows("reanalysis_synoptic", 0.02),
                    }
                ),
                encoding="utf-8",
            )

            payload = build_ratchet(
                source_family_inventory=inventory,
                source_family_ablation=ablation,
                generated_at_utc="2026-06-23T00:00:00+00:00",
            )
            by_family = {row["family_id"]: row for row in payload["families"]}
            report = render_report(payload)
            json_out, report_out = write_outputs(payload, root / "ratchet.json", root / "ratchet.md")
            json_exists = json_out.exists()
            report_exists = report_out.exists()

        self.assertEqual(payload["schema_version"], "physical_feature_family_ratchet_v0.1")
        self.assertEqual(payload["status"], "BLOCK")
        self.assertEqual(by_family["forecast_baseline"]["status"], "PROMOTION_ELIGIBLE")
        self.assertEqual(by_family["open_meteo_expanded"]["status"], "ISOLATED_REPLAY_BLOCK")
        self.assertEqual(by_family["nws_grid"]["status"], "LINEAGE_BLOCKED")
        self.assertEqual(by_family["multi_model_guidance"]["status"], "LIVE_ONLY")
        self.assertEqual(by_family["mrms_precip"]["status"], "MISSING_ACTIVE_ARTIFACT")
        self.assertEqual(by_family["marine_context"]["status"], "MISSING_SETTLED_REPLAY")
        self.assertEqual(by_family["reanalysis_synoptic"]["status"], "ISOLATED_REPLAY_BLOCK")
        self.assertEqual(payload["excluded_market_overlay_families"][0]["family_id"], "clob_microstructure")
        self.assertIn("forecast_baseline", payload["rollup"]["ready_for_retraining"])
        self.assertIn("Settlement-Sliced Lift And Harm", report)
        self.assertTrue(json_exists)
        self.assertTrue(report_exists)


if __name__ == "__main__":
    unittest.main()
