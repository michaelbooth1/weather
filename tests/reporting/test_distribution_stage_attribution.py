import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.distribution_stage_attribution import (
    build_payload,
    render_report,
    write_outputs,
)
from weather.schema_registry import schema_version


def _write_fixture(root):
    folder = Path(root) / "highest-temperature-in-test-on-june-1-2026"
    folder.mkdir(parents=True)
    (folder / "settlement.json").write_text(
        json.dumps({
            "event_slug": folder.name,
            "market_id": "test",
            "target_date": "2026-06-01",
            "settlement_bucket": 22,
            "settlement_unit": "F",
        }),
        encoding="utf-8",
    )
    header = [
        "snapshot_id",
        "captured_at_local",
        "event_slug",
        "cutoff_hour",
        "active_model_kind",
        "component_name",
        "range_label",
        "bin_kind",
        "bin_value_c",
        "component_probability",
    ]
    rows = []
    for component, losing_p, winning_p in [
        ("climatology_prior", 0.20, 0.40),
        ("feature_blend", 0.10, 0.70),
        ("post_live_signals", 0.40, 0.60),
        ("final_model", 0.10, 0.80),
    ]:
        rows.append({
            "snapshot_id": "s1",
            "captured_at_local": "2026-06-01T12:00:00-04:00",
            "event_slug": folder.name,
            "cutoff_hour": "12",
            "active_model_kind": "hgb",
            "component_name": component,
            "range_label": "20 F or below",
            "bin_kind": "lte",
            "bin_value_c": "20",
            "component_probability": losing_p,
        })
        rows.append({
            "snapshot_id": "s1",
            "captured_at_local": "2026-06-01T12:00:00-04:00",
            "event_slug": folder.name,
            "cutoff_hour": "12",
            "active_model_kind": "hgb",
            "component_name": component,
            "range_label": "22-23 F",
            "bin_kind": "eq",
            "bin_value_c": "22",
            "component_probability": winning_p,
        })
    with (folder / "components_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    return folder


class DistributionStageAttributionTests(unittest.TestCase):
    def test_build_payload_scores_stage_deltas_and_flags_net_negative_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_fixture(tmp)
            payload = build_payload(tmp, min_stage_rows=1, now="2026-06-21T00:00:00+00:00")

        self.assertEqual(payload["schema_version"], schema_version("distribution_stage_attribution"))
        self.assertEqual(payload["status"], "ACTIONABLE")
        self.assertEqual(payload["settled_folder_count"], 1)
        self.assertEqual(payload["attribution_row_count"], 8)
        by_component = {row["group"]: row for row in payload["by_component"]}
        self.assertGreater(by_component["post_live_signals"]["mean_delta_brier"], 0.0)
        self.assertLess(by_component["feature_blend"]["mean_delta_brier"], 0.0)
        self.assertEqual(payload["by_regime"][0]["group"], "hgb")
        self.assertEqual(payload["net_negative_stages"][0]["group"], "post_live_signals")

    def test_write_outputs_emits_json_and_markdown_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_fixture(Path(tmp) / "snapshots")
            payload = build_payload(Path(tmp) / "snapshots", min_stage_rows=1)
            json_out, report_out = write_outputs(
                payload,
                Path(tmp) / "out.json",
                Path(tmp) / "out.md",
            )

            saved = json.loads(json_out.read_text(encoding="utf-8"))
            report = report_out.read_text(encoding="utf-8")

        self.assertEqual(saved["status"], "ACTIONABLE")
        self.assertIn("Distribution Stage Attribution", report)
        self.assertIn("post_live_signals", report)
        self.assertIn("Positive deltas", render_report(payload))


if __name__ == "__main__":
    unittest.main()
