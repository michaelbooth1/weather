import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from weather.reporting.disagreement_casebook import (  # noqa: E402
    build_arg_parser,
    build_casebook,
    clean_label,
    write_outputs,
)


SNAPSHOT_COLUMNS = [
    "snapshot_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "event_updated_at",
    "model_version",
    "top_temp_c",
    "top_probability",
    "range_label",
    "bin_kind",
    "bin_value_c",
    "model_probability",
    "market_yes",
    "market_no",
    "edge",
    "best_bid",
    "best_ask",
    "last_trade_price",
    "volume",
    "liquidity",
    "market_status",
    "wu_history_high_c",
    "wu_current_c",
    "wu_max_since_7am_c",
    "eccc_swob_max_c",
    "weather_forecast_max_c",
    "open_meteo_max_c",
    "nws_forecast_max_c",
    "global_ensemble_max_c",
    "forecast_source_count",
    "forecast_disagreement",
    "eccc_forecast_high_c",
]

COMPONENT_COLUMNS = [
    "snapshot_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "model_version",
    "component_schema_version",
    "cutoff_hour",
    "active_model_kind",
    "component_name",
    "range_label",
    "bin_kind",
    "bin_value_c",
    "component_probability",
    "market_yes",
]

BOOK_COLUMNS = [
    "capture_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "market_id",
    "polymarket_market_id",
    "condition_id",
    "range_label",
    "bin_kind",
    "bin_value",
    "bin_value_hi",
    "unit",
    "outcome",
    "clob_token_id",
    "order_book_hash",
    "book_timestamp",
    "book_time_utc",
    "min_order_size",
    "tick_size",
    "neg_risk",
    "bid_count",
    "ask_count",
    "best_bid",
    "best_ask",
    "spread",
    "midpoint",
    "bid_size_at_best",
    "ask_size_at_best",
    "bid_depth_1pct",
    "ask_depth_1pct",
    "bid_depth_5pct",
    "ask_depth_5pct",
    "bid_depth_all",
    "ask_depth_all",
    "imbalance_1pct",
    "imbalance_5pct",
    "last_trade_price",
]


class TestDisagreementCasebook(unittest.TestCase):
    def write_folder(self, root):
        folder = Path(root) / "highest-temperature-in-toronto-on-june-7-2026"
        folder.mkdir(parents=True)
        snapshots = [
            ("s1", "2026-06-07T14:00:00+00:00", "2026-06-07T10:00:00-04:00", 0.18, 0.20, 24),
            ("s2", "2026-06-07T14:10:00+00:00", "2026-06-07T10:10:00-04:00", 0.32, 0.05, 24),
            ("s3", "2026-06-07T14:20:00+00:00", "2026-06-07T10:20:00-04:00", 0.28, 0.06, 24),
        ]
        rows = []
        for snapshot_id, utc_time, local_time, model_p, market_p, wu_high in snapshots:
            rows.append({
                "snapshot_id": snapshot_id,
                "captured_at_utc": utc_time,
                "captured_at_local": local_time,
                "event_slug": folder.name,
                "event_updated_at": utc_time,
                "model_version": "test-model",
                "top_temp_c": 24,
                "top_probability": model_p,
                "range_label": "24\u00c2\u00b0C",
                "bin_kind": "eq",
                "bin_value_c": 24,
                "model_probability": model_p,
                "market_yes": market_p,
                "market_no": 1 - market_p,
                "edge": model_p - market_p,
                "best_bid": market_p - 0.01,
                "best_ask": market_p + 0.01,
                "last_trade_price": market_p,
                "volume": 100,
                "liquidity": 1000,
                "market_status": "active",
                "wu_history_high_c": wu_high,
                "wu_current_c": wu_high,
                "wu_max_since_7am_c": wu_high,
                "eccc_swob_max_c": wu_high,
                "weather_forecast_max_c": 24,
                "open_meteo_max_c": 24,
                "nws_forecast_max_c": "",
                "global_ensemble_max_c": "",
                "forecast_source_count": 2,
                "forecast_disagreement": 0,
                "eccc_forecast_high_c": "",
            })
        with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=SNAPSHOT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

        component_rows = []
        for snapshot_id, utc_time, local_time, _model_p, _market_p, _wu_high in snapshots:
            for component, probability in [
                ("climatology_prior", 0.20),
                ("feature_blend", 0.30),
                ("final_model", 0.34 if snapshot_id == "s3" else 0.32),
            ]:
                component_rows.append({
                    "snapshot_id": snapshot_id,
                    "captured_at_utc": utc_time,
                    "captured_at_local": local_time,
                    "event_slug": folder.name,
                    "model_version": "test-model",
                    "component_schema_version": "test-components",
                    "cutoff_hour": 10,
                    "active_model_kind": "hgb",
                    "component_name": component,
                    "range_label": "24\u00c2\u00b0C",
                    "bin_kind": "eq",
                    "bin_value_c": 24,
                    "component_probability": probability,
                    "market_yes": 0.05,
                })
        with (folder / "components_long.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COMPONENT_COLUMNS)
            writer.writeheader()
            writer.writerows(component_rows)

        with (folder / "replay_inputs.jsonl").open("w", encoding="utf-8") as handle:
            for snapshot_id, utc_time, local_time, *_rest in snapshots:
                handle.write(json.dumps({
                    "snapshot_id": snapshot_id,
                    "captured_at_utc": utc_time,
                    "captured_at_local": local_time,
                    "model_identity": {"identity_hash": "abc"},
                    "sources": {
                        "wu_current": {
                            "ok": True,
                            "stale": False,
                            "status": "fresh",
                            "fetched_at": local_time,
                        }
                    },
                }) + "\n")

        with (folder / "settlement.json").open("w", encoding="utf-8") as handle:
            json.dump({
                "event_slug": folder.name,
                "market_id": "toronto",
                "settlement_bucket": 24,
                "settlement_high": 24,
                "settlement_unit": "C",
                "winning_band": "24 C",
                "quality_grade": "complete",
                "settlement_source": "daily_summary",
                "reconciliation_status": "match",
            }, handle)

        book_rows = []
        for idx, (minute, second, midpoint) in enumerate([(9, 0, 0.40), (9, 59, 0.30)]):
            book_rows.append({
                "capture_id": f"b{idx}",
                "captured_at_utc": f"2026-06-07T14:{minute:02d}:{second:02d}+00:00",
                "captured_at_local": f"2026-06-07T10:{minute:02d}:{second:02d}-04:00",
                "event_slug": folder.name,
                "market_id": "toronto",
                "polymarket_market_id": "m1",
                "condition_id": "c1",
                "range_label": "24\u00c2\u00b0C",
                "bin_kind": "eq",
                "bin_value": 24,
                "bin_value_hi": 24,
                "unit": "C",
                "outcome": "Yes",
                "clob_token_id": "yes-token",
                "order_book_hash": "h",
                "book_timestamp": "",
                "book_time_utc": "",
                "min_order_size": 1,
                "tick_size": 0.001,
                "neg_risk": "true",
                "bid_count": 1,
                "ask_count": 1,
                "best_bid": midpoint - 0.01,
                "best_ask": midpoint + 0.01,
                "spread": 0.02,
                "midpoint": midpoint,
                "bid_size_at_best": 10,
                "ask_size_at_best": 10,
                "bid_depth_1pct": 10,
                "ask_depth_1pct": 10,
                "bid_depth_5pct": 20,
                "ask_depth_5pct": 20,
                "bid_depth_all": 30,
                "ask_depth_all": 30,
                "imbalance_1pct": 0,
                "imbalance_5pct": 0,
                "last_trade_price": midpoint,
            })
        with (folder / "order_books_summary.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=BOOK_COLUMNS)
            writer.writeheader()
            writer.writerows(book_rows)
        return folder

    def test_casebook_collapses_threshold_snapshots_and_scores_settlement(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.write_folder(tmp)
            args = build_arg_parser().parse_args([
                str(folder),
                "--edge-threshold",
                "0.10",
                "--clob-midpoint-move",
                "0.05",
            ])

            payload = build_casebook(
                folders=[str(folder)],
                snapshots_root=tmp,
                backtest_root=Path(tmp) / "backtest",
                args=args,
            )

        self.assertEqual(payload["summary"]["case_count"], 1)
        self.assertTrue(payload["summary"]["threshold_coverage_ok"])
        case = payload["cases"][0]
        self.assertEqual(case["range_label"], "24 C")
        self.assertEqual(case["peak_snapshot"]["range_label"], "24 C")
        self.assertEqual(case["start_time_utc"], "2026-06-07T14:10:00+00:00")
        self.assertEqual(case["end_time_utc"], "2026-06-07T14:20:00+00:00")
        self.assertEqual(case["source_values"]["wu_history_high_c"], 24.0)
        self.assertEqual(case["threshold_snapshot_count"], 2)
        self.assertIn("absolute_edge", case["trigger_reasons"])
        self.assertIn("market_price_collapse_model_high", case["trigger_reasons"])
        self.assertIn("large_clob_midpoint_move", case["trigger_reasons"])
        self.assertEqual(case["model_result"], "model_win")
        self.assertEqual(case["taxonomy"], "market_overreaction")
        self.assertEqual(case["outcome"], 1)
        self.assertLess(case["model_brier"], case["market_brier"])
        self.assertTrue(case["driver_waterfall"])
        self.assertEqual(case["source_freshness"]["wu_current"]["status"], "fresh")
        self.assertAlmostEqual(case["clob_context"]["midpoint_move_abs"], 0.10)
        self.assertEqual(payload["feedback_slices"][0]["slice_type"], "known_edge_candidate")
        self.assertEqual(payload["feedback_slices"][0]["snapshot_refs"][0]["range_label"], "24 C")

    def test_write_outputs_creates_json_report_and_operator_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.write_folder(tmp)
            args = build_arg_parser().parse_args([str(folder), "--edge-threshold", "0.10"])
            payload = build_casebook(
                folders=[str(folder)],
                snapshots_root=tmp,
                backtest_root=Path(tmp) / "backtest",
                args=args,
            )
            json_out = Path(tmp) / "casebook.json"
            report_out = Path(tmp) / "casebook.md"
            operator_out = Path(tmp) / "operator.md"

            write_outputs(payload, json_out, report_out, operator_out)

            self.assertTrue(json_out.exists())
            self.assertTrue(report_out.exists())
            self.assertTrue(operator_out.exists())
            report = report_out.read_text(encoding="utf-8")
            self.assertIn("## Design", report)
            self.assertIn("## Top Model-Losing Case Families", report)
            self.assertIn("## Feedback Slices", report)
            self.assertNotIn("\u00c2\u00b0C", report)

    def test_clean_label_scrubs_degree_mojibake(self):
        self.assertEqual(clean_label("90-91\u00c2\u00b0F"), "90-91 F")
        self.assertEqual(clean_label("25\u00b0C"), "25 C")


if __name__ == "__main__":
    unittest.main()
