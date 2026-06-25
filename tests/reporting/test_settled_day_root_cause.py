import csv
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from weather.reporting.scorecards.settled_day_root_cause import (
    build_payload,
    render_report,
    roadmap_mappings,
    write_outputs,
)
from weather.schema_registry import schema_version


def _write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_fixture(root):
    root = Path(root)
    snapshots = root / "snapshots"
    folder = snapshots / "highest-temperature-in-nyc-on-june-20-2026"
    folder.mkdir(parents=True)
    (folder / "settlement.json").write_text(
        json.dumps({
            "event_slug": folder.name,
            "market_id": "nyc",
            "target_date": "2026-06-20",
            "settlement_bucket": 82,
            "settlement_unit": "F",
        }),
        encoding="utf-8",
    )
    snapshot_fields = [
        "snapshot_id",
        "captured_at_local",
        "event_slug",
        "range_label",
        "bin_kind",
        "bin_value_c",
        "bin_value_hi_c",
        "model_probability",
        "market_yes",
        "forecast_disagreement",
        "wu_history_high_c",
        "wu_current_c",
        "wu_max_since_7am_c",
    ]
    _write_csv(
        folder / "snapshots_long.csv",
        snapshot_fields,
        [
            {
                "snapshot_id": "s0",
                "captured_at_local": "2026-06-20T00:05:00-04:00",
                "event_slug": folder.name,
                "range_label": "82-83 F",
                "bin_kind": "eq",
                "bin_value_c": "82",
                "bin_value_hi_c": "83",
                "model_probability": "0.70",
                "market_yes": "0.60",
                "forecast_disagreement": "0.0",
                "wu_history_high_c": "17",
                "wu_current_c": "17",
                "wu_max_since_7am_c": "",
            },
            {
                "snapshot_id": "s1",
                "captured_at_local": "2026-06-20T12:00:00-04:00",
                "event_slug": folder.name,
                "range_label": "82-83 F",
                "bin_kind": "eq",
                "bin_value_c": "82",
                "bin_value_hi_c": "83",
                "model_probability": "0.10",
                "market_yes": "0.55",
                "forecast_disagreement": "6.0",
                "wu_history_high_c": "82",
                "wu_current_c": "81",
                "wu_max_since_7am_c": "92",
            },
            {
                "snapshot_id": "s1",
                "captured_at_local": "2026-06-20T12:00:00-04:00",
                "event_slug": folder.name,
                "range_label": "86-87 F",
                "bin_kind": "eq",
                "bin_value_c": "86",
                "bin_value_hi_c": "87",
                "model_probability": "0.60",
                "market_yes": "0.10",
                "forecast_disagreement": "6.0",
                "wu_history_high_c": "82",
                "wu_current_c": "81",
                "wu_max_since_7am_c": "92",
            },
        ],
    )
    feature_fields = ["snapshot_id", "high_so_far", "current_temp", "forecast_disagreement", "live_reading_minus_high"]
    _write_csv(
        folder / "features_long.csv",
        feature_fields,
        [
            {
                "snapshot_id": "s0",
                "high_so_far": "17",
                "current_temp": "17",
                "forecast_disagreement": "0",
                "live_reading_minus_high": "0",
            },
            {
                "snapshot_id": "s1",
                "high_so_far": "82",
                "current_temp": "81",
                "forecast_disagreement": "6",
                "live_reading_minus_high": "-1",
            },
        ],
    )
    explanation_fields = [
        "snapshot_id",
        "section",
        "item_key",
        "item_subkey",
        "source_hash",
        "model_identity_hash",
        "payload_hash",
    ]
    _write_csv(
        folder / "snapshot_explanations_long.csv",
        explanation_fields,
        [
            {
                "snapshot_id": "s1",
                "section": "model_explanation",
                "item_key": "driver_breakdown",
                "item_subkey": "",
                "source_hash": "source-hash",
                "model_identity_hash": "model-hash",
                "payload_hash": "payload-hash",
            },
            {
                "snapshot_id": "s1",
                "section": "analog_search",
                "item_key": "neighbors",
                "item_subkey": "",
                "source_hash": "source-hash",
                "model_identity_hash": "model-hash",
                "payload_hash": "analog-hash",
            },
        ],
    )
    price_history_fields = [
        "captured_at_utc",
        "captured_at_local",
        "event_slug",
        "market_id",
        "polymarket_market_id",
        "condition_id",
        "range_label",
        "outcome",
        "clob_token_id",
        "interval",
        "fidelity_minutes",
        "point_timestamp",
        "point_time_utc",
        "price",
    ]
    _write_csv(
        folder / "price_history.csv",
        price_history_fields,
        [
            {
                "captured_at_utc": "2026-06-20T16:00:00+00:00",
                "captured_at_local": "2026-06-20T12:00:00-04:00",
                "event_slug": folder.name,
                "market_id": "nyc",
                "polymarket_market_id": "m1",
                "condition_id": "c1",
                "range_label": "82-83 F",
                "outcome": "Yes",
                "clob_token_id": "winner-token",
                "interval": "1m",
                "fidelity_minutes": "1",
                "point_timestamp": "",
                "point_time_utc": "2026-06-20T15:57:00+00:00",
                "price": "0.45",
            },
            {
                "captured_at_utc": "2026-06-20T16:00:00+00:00",
                "captured_at_local": "2026-06-20T12:00:00-04:00",
                "event_slug": folder.name,
                "market_id": "nyc",
                "polymarket_market_id": "m1",
                "condition_id": "c1",
                "range_label": "82-83 F",
                "outcome": "Yes",
                "clob_token_id": "winner-token",
                "interval": "1m",
                "fidelity_minutes": "1",
                "point_timestamp": "",
                "point_time_utc": "2026-06-20T16:00:00+00:00",
                "price": "0.55",
            },
        ],
    )
    _write_csv(
        folder / "market_ws_events.csv",
        ["received_at_utc", "event_slug", "market_id", "event_type", "asset_id", "market", "price", "side", "raw_sha1"],
        [{
            "received_at_utc": "2026-06-20T16:00:05+00:00",
            "event_slug": folder.name,
            "market_id": "nyc",
            "event_type": "price_change",
            "asset_id": "winner-token",
            "market": "c1",
            "price": "0.55",
            "side": "BUY",
            "raw_sha1": "ws-hash",
        }],
    )

    taker = root / "taker_runs" / "2026-06-20" / "taker-20260620-test"
    taker.mkdir(parents=True)
    (taker / "daily_pnl.json").write_text(
        json.dumps({"net_pnl_usdc": -5.0, "by_market": [{"market_id": "nyc", "net_pnl_usdc": -5.0}]}),
        encoding="utf-8",
    )
    order_fields = [
        "market_id",
        "event_slug",
        "snapshot_id",
        "capture_hour_local",
        "range_label",
        "bin_value",
        "fill_price",
        "fill_notional_usdc",
        "net_pnl_usdc",
        "settlement_current_high",
        "fair_probability",
        "current_max_disposition",
    ]
    _write_csv(
        taker / "orders_long.csv",
        order_fields,
        [{
            "market_id": "nyc",
            "event_slug": folder.name,
            "snapshot_id": "s1",
            "capture_hour_local": "12",
            "range_label": "86-87 F",
            "bin_value": "86",
            "fill_price": "0.20",
            "fill_notional_usdc": "5.00",
            "net_pnl_usdc": "-5.00",
            "settlement_current_high": "82",
            "fair_probability": "0.60",
            "current_max_disposition": "validated",
        }],
    )

    mm_run = root / "mm_runs" / "2026-06-20" / "20260620T120000Z"
    mm_run.mkdir(parents=True)
    (mm_run / "run_summary.json").write_text(
        json.dumps({"cumulative": {"blocked_by_preflight_count": 3}}),
        encoding="utf-8",
    )
    (mm_run / "preflight.json").write_text(
        json.dumps({"markets": [{"market_id": "nyc", "book_audit": {"reason": "last book capture is stale"}}]}),
        encoding="utf-8",
    )
    _write_csv(mm_run / "fills_long.csv", ["id"], [])

    backtest = root / "backtest"
    backtest.mkdir()
    (backtest / "hourly_model_performance_2026-06-20.json").write_text(
        json.dumps({"all_snapshot_by_hour": [{"hour_label": "12:00", "brier_delta": -0.1, "snapshots": 1}]}),
        encoding="utf-8",
    )
    return snapshots, taker, root / "taker_runs", root / "mm_runs", backtest


def _roadmap_item(root: Path, number: int, title: str, status: str) -> None:
    items = root / "items"
    items.mkdir(parents=True, exist_ok=True)
    (items / f"item-{number:03d}-{title.lower().replace(' ', '-')}.md").write_text(
        f"# {number}. {title} [{status}]\n",
        encoding="utf-8",
    )


def _write_labels_csv(path: Path, latest_target_date: str = "2026-06-20") -> Path:
    rows = [
        {
            "event_slug": "highest-temperature-in-nyc-on-june-20-2026",
            "market_id": "nyc",
            "target_date": "2026-06-20",
            "quality_grade": "complete",
            "settlement_bucket": "82",
        },
        {
            "event_slug": f"highest-temperature-in-nyc-on-{latest_target_date}",
            "market_id": "nyc",
            "target_date": latest_target_date,
            "quality_grade": "complete",
            "settlement_bucket": "82",
        },
    ]
    _write_csv(path, list(rows[0]), rows)
    return path


class SettledDayRootCauseTests(unittest.TestCase):
    def test_build_payload_maps_detected_issue_codes_to_roadmap_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshots, taker, taker_root, mm_root, backtest = _write_fixture(tmp)
            payload = build_payload(
                "2026-06-20",
                snapshots_root=snapshots,
                taker_run_folder=taker,
                taker_root=taker_root,
                mm_root=mm_root,
                backtest_root=backtest,
                now="2026-06-21T00:00:00+00:00",
            )

        self.assertEqual(payload["schema_version"], schema_version("settled_day_root_cause"))
        self.assertEqual(payload["status"], "ACTIONABLE")
        issue_counts = payload["summary"]["issue_counts"]
        self.assertIn("MODEL_TOP_WARM_SIDE_MISS", issue_counts)
        self.assertIn("WU_CURRENT_MAX_ANOMALY", issue_counts)
        self.assertIn("STARTUP_LIVE_OBSERVATION_IMPLAUSIBLE", issue_counts)
        self.assertIn("TAKER_BOUGHT_WARM_TAIL", issue_counts)
        by_issue = {row["issue_code"]: row for row in payload["roadmap_mappings"]}
        self.assertIn("195", by_issue["RAMP_WINDOW_WARM_TAIL_SPREAD"]["roadmap_items"])
        self.assertIn("193", by_issue["WU_CURRENT_MAX_ANOMALY"]["roadmap_items"])
        self.assertEqual(by_issue["WU_CURRENT_MAX_ANOMALY"]["classification"], "historical_closure_evidence")
        self.assertIn("160", by_issue["MODEL_WEAK_HOUR_SLOT"]["active_owner_items"])
        self.assertNotIn("192", by_issue["MODEL_WEAK_HOUR_SLOT"]["roadmap_items"])
        self.assertIn("210", by_issue["MM_PREFLIGHT_STALE_BOOKS"]["roadmap_items"])
        self.assertIn("161", by_issue["MM_PREFLIGHT_STALE_BOOKS"]["active_owner_items"])
        self.assertIn("157", by_issue["MM_PREFLIGHT_STALE_BOOKS"]["active_owner_items"])
        self.assertIn("161", by_issue["MM_PREFLIGHT_STALE_BOOKS"]["roadmap_items"])
        self.assertIn("157", by_issue["MM_PREFLIGHT_STALE_BOOKS"]["roadmap_items"])
        self.assertNotIn("198", by_issue["MM_PREFLIGHT_STALE_BOOKS"]["roadmap_items"])
        self.assertEqual(payload["summary"]["new_roadmap_item_candidate_count"], 0)
        self.assertEqual(payload["summary"]["explanation_snapshot_count"], 1)
        self.assertIn("model_explanation", payload["summary"]["explanation_sections"])
        self.assertEqual(payload["summary"]["price_history_snapshot_count"], 1)
        self.assertEqual(payload["summary"]["ws_event_snapshot_count"], 1)
        market = payload["markets"][0]
        self.assertEqual(market["explanation_snapshot_count"], 1)
        self.assertIn("analog_search", market["explanation_sections"])
        self.assertEqual(market["price_history_snapshot_count"], 1)
        self.assertEqual(market["ws_event_snapshot_count"], 1)

    def test_build_payload_blocks_when_root_cause_target_lags_latest_settled_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshots, taker, taker_root, mm_root, backtest = _write_fixture(tmp)
            labels_csv = _write_labels_csv(backtest / "market_day_labels.csv", latest_target_date="2026-06-21")

            payload = build_payload(
                "2026-06-20",
                snapshots_root=snapshots,
                taker_run_folder=taker,
                taker_root=taker_root,
                mm_root=mm_root,
                backtest_root=backtest,
                labels_csv=labels_csv,
            )

        self.assertEqual(payload["status"], "BLOCK")
        self.assertEqual(payload["last_scored_target_date"], "2026-06-20")
        self.assertEqual(payload["latest_settled_label_date"], "2026-06-21")
        self.assertEqual(payload["scoring_liveness"]["status"], "BLOCK")
        self.assertIn(
            "python -m weather.reporting.scorecards.settled_day_root_cause",
            payload["scoring_liveness"]["remediation_command"],
        )

    def test_write_outputs_emits_json_markdown_and_issue_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshots, taker, taker_root, mm_root, backtest = _write_fixture(tmp)
            payload = build_payload(
                "2026-06-20",
                snapshots_root=snapshots,
                taker_run_folder=taker,
                taker_root=taker_root,
                mm_root=mm_root,
                backtest_root=backtest,
            )
            json_out, report_out, issues_out = write_outputs(
                payload,
                Path(tmp) / "out.json",
                Path(tmp) / "out.md",
                Path(tmp) / "issues.csv",
            )

            saved = json.loads(json_out.read_text(encoding="utf-8"))
            report = report_out.read_text(encoding="utf-8")
            issue_rows = list(csv.DictReader(issues_out.open("r", encoding="utf-8")))

        self.assertEqual(saved["status"], "ACTIONABLE")
        self.assertIn("Settled-Day Root-Cause Report", report)
        self.assertIn("Explanation coverage", report)
        self.assertIn("Price-history coverage", report)
        self.assertIn("WS Event Snapshots", report)
        self.assertIn("TAKER_BOUGHT_WARM_TAIL", render_report(payload))
        self.assertTrue(issue_rows)
        self.assertIn("roadmap_classification", issue_rows[0])
        self.assertIn("active_owner_items", issue_rows[0])

    def test_roadmap_mapping_flags_post_closure_recurrence_without_active_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            roadmap_root = Path(tmp) / "roadmap"
            _roadmap_item(
                roadmap_root,
                193,
                "WU Current-Max Anomaly Quarantine And Trust Weighting",
                "COMPLETE 2026-06-21 - DONE",
            )

            rows = roadmap_mappings(
                Counter({"WU_CURRENT_MAX_ANOMALY": 2}),
                issue_date="2026-06-22",
                roadmap_root=roadmap_root,
            )

        self.assertEqual(rows[0]["classification"], "post_closure_recurrence")
        self.assertEqual(rows[0]["active_owner_items"], [])
        self.assertEqual(
            rows[0]["suggested_new_item_title"],
            "Post-Closure WU Current-Max Anomaly Recurrence",
        )


if __name__ == "__main__":
    unittest.main()
