import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from mm_policy import (
    apply_known_edge_permission,
    config_with_clob_recon,
    decide_quote,
    resolve_known_edge_record,
    run_policy_snapshot,
)


NOW = "2026-06-14T16:00:00+00:00"


def fresh_row(**overrides):
    row = {
        "market_id": "atlanta",
        "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
        "snapshot_id": "s1",
        "captured_at_utc": "2026-06-14T15:59:30+00:00",
        "model_version": "candidate",
        "promotion_state": "SHADOW",
        "range_label": "80-81 F",
        "bin_kind": "eq",
        "bin_value": "80",
        "bin_value_hi": "81",
        "clob_token_id": "token-1",
        "condition_id": "condition-1",
        "fair_probability": 0.51,
        "market_mid": 0.50,
        "market_yes": 0.50,
        "clob_spread": 0.02,
        "clob_best_bid": 0.49,
        "clob_best_ask": 0.51,
        "clob_depth_1pct_total": 100.0,
        "clob_book_age_seconds": 20.0,
        "watcher_age_seconds": 10.0,
        "source_fresh": True,
        "heartbeat_ok": True,
        "market_status": "active",
    }
    row.update(overrides)
    return row


def write_known_edge_map(path, records):
    path.write_text(json.dumps({
        "schema_version": "mm_known_edge_map_v0.1",
        "records": records,
        "summary": {"record_count": len(records)},
    }), encoding="utf-8")
    return path


def manual_event_calendar(action="suppress"):
    return {
        "manual_events": [
            {
                "event_id": "platform-maintenance-1",
                "market_id": "atlanta",
                "event_class": "platform_maintenance",
                "label": "platform maintenance",
                "starts_at_utc": "2026-06-14T15:59:00+00:00",
                "ends_at_utc": "2026-06-14T16:01:00+00:00",
                "action": action,
                "reason_code": "INFO_EVENT_PLATFORM_MAINTENANCE",
            }
        ],
    }


class TestMmPolicy(unittest.TestCase):
    def test_blocked_promotion_fails_closed(self):
        quote = decide_quote(fresh_row(promotion_state="BLOCK"), now=NOW)

        self.assertFalse(quote["quote_permission"])
        self.assertFalse(quote["live_trade_permission"])
        self.assertEqual(quote["reason_code"], "NO_QUOTE_BLOCKED_PROMOTION")

    def test_shadow_harvest_quotes_when_fresh_and_small_edge(self):
        quote = decide_quote(fresh_row(), now=NOW)

        self.assertTrue(quote["quote_permission"])
        self.assertFalse(quote["live_trade_permission"])
        self.assertEqual(quote["regime"], "harvest")
        self.assertEqual(quote["reason_code"], "QUOTE_HARVEST_MID")
        self.assertLess(quote["bid_price"], quote["ask_price"])
        self.assertIn(quote["event_gate_status"], {"CLEAR", "WIDEN"})

    def test_information_event_gate_suppresses_quote(self):
        quote = decide_quote(
            fresh_row(),
            config={"_information_event_calendar_config": manual_event_calendar()},
            now=NOW,
        )

        self.assertFalse(quote["quote_permission"])
        self.assertEqual(quote["reason_code"], "NO_QUOTE_INFORMATION_EVENT")
        self.assertEqual(quote["event_gate_status"], "PULL")
        self.assertEqual(quote["event_gate_action"], "suppress")
        self.assertEqual(quote["event_gate_event_class"], "platform_maintenance")
        self.assertEqual(quote["event_gate_reason_code"], "INFO_EVENT_PLATFORM_MAINTENANCE")

    def test_information_event_exception_requires_evidence_and_caps_size(self):
        quote = decide_quote(
            fresh_row(),
            config={
                "_information_event_calendar_config": manual_event_calendar(),
                "event_gate_exception_enabled": True,
                "event_gate_exception_event_classes": "platform_maintenance",
                "event_gate_exception_evidence_status": "PAPER_PASS",
                "event_gate_exception_evidence_id": "paper-slice-1",
                "event_gate_exception_risk_cap_usdc": 1.0,
            },
            now=NOW,
        )

        self.assertTrue(quote["quote_permission"])
        self.assertEqual(quote["event_gate_status"], "EXCEPTION")
        self.assertEqual(quote["event_gate_action"], "allow_exception")
        self.assertEqual(quote["event_gate_exception_id"], "paper-slice-1")
        self.assertEqual(quote["final_size_limiter"], "event_gate_exception_risk_cap")
        self.assertLess(float(quote["bid_size"]), 2.0)

    def test_clob_recon_policy_overrides_apply_when_artifact_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clob_recon.json"
            path.write_text(json.dumps({
                "schema_version": "clob_book_recon_v0.1",
                "policy_parameter_suggestions": {
                    "quote_size": 2.0,
                    "harvest_half_spread": 0.02,
                    "min_depth_1pct_total": 4.0,
                    "reward_competitor_q": 50.0,
                },
                "summary": {"slice_rows": 3},
            }), encoding="utf-8")

            config, diag = config_with_clob_recon({
                "clob_recon_policy_enabled": True,
                "clob_recon_path": str(path),
                "quote_size": 5.0,
            })

        self.assertTrue(diag["exists"])
        self.assertEqual(config["quote_size"], 2.0)
        self.assertEqual(config["harvest_half_spread"], 0.02)
        self.assertNotIn("reward_competitor_q", config)

    def test_shadow_large_disagreement_stands_down(self):
        quote = decide_quote(fresh_row(fair_probability=0.70, market_mid=0.50), now=NOW)

        self.assertFalse(quote["quote_permission"])
        self.assertEqual(quote["reason_code"], "NO_QUOTE_DISAGREEMENT_SHADOW")

    def test_pass_known_edge_can_emit_model_skewed_quote(self):
        quote = decide_quote(
            fresh_row(
                promotion_state="PASS",
                known_edge_allowed=True,
                known_edge_permission="edge_allowed",
                known_edge_reason="live_forward_paper_gate_clear",
                known_edge_record_key="atlanta|*|*|*|*|*|*|*|*",
                known_edge_taxonomy="book_liquidity_artifact",
                fair_probability=0.60,
                market_mid=0.50,
                clob_best_bid=0.49,
                clob_best_ask=0.56,
            ),
            now=NOW,
        )

        self.assertTrue(quote["quote_permission"])
        self.assertEqual(quote["regime"], "edge")
        self.assertEqual(quote["side"], "YES_BID")
        self.assertEqual(quote["reason_code"], "QUOTE_EDGE_MODEL")

    def test_clob_overlay_market_informed_record_does_not_enable_edge_quote(self):
        row = fresh_row(
            promotion_state="PASS",
            casebook_taxonomy="market_lead",
            fair_probability=0.60,
            market_mid=0.50,
            clob_best_bid=0.49,
            clob_best_ask=0.56,
        )
        records = [
            {
                "market_id": "*",
                "cutoff": "*",
                "hour_utc": "*",
                "band_distance_bucket": "*",
                "band_type": "*",
                "casebook_taxonomy": "market_lead",
                "regime": "*",
                "source_fresh": "*",
                "source_freshness_state": "*",
                "book_imbalance_bucket": "*",
                "base_permission": "CLOB_OVERLAY_MARKET_INFORMED",
                "permission": "edge_research",
                "reason": "clob_overlay_market_informed_replay_gate_clear",
            }
        ]

        record = resolve_known_edge_record(row, records)
        merged = apply_known_edge_permission(row, record=record, map_loaded=True)
        quote = decide_quote(merged, now=NOW)

        self.assertFalse(quote["known_edge_allowed"])
        self.assertEqual(quote["known_edge_taxonomy"], "market_lead")
        self.assertEqual(quote["known_edge_reason"], "clob_overlay_market_informed_replay_gate_clear")
        self.assertFalse(quote["quote_permission"])
        self.assertEqual(quote["regime"], "none")
        self.assertEqual(quote["reason_code"], "NO_QUOTE_DISAGREEMENT_SHADOW")

    def test_no_quote_known_edge_permission_fails_closed(self):
        quote = decide_quote(
            fresh_row(
                promotion_state="PASS",
                known_edge_allowed=True,
                known_edge_permission="no_quote",
                known_edge_reason="promotion_block",
                fair_probability=0.70,
                market_mid=0.50,
            ),
            now=NOW,
        )

        self.assertFalse(quote["quote_permission"])
        self.assertFalse(quote["known_edge_allowed"])
        self.assertEqual(quote["known_edge_permission"], "no_quote")
        self.assertEqual(quote["reason_code"], "NO_QUOTE_KNOWN_EDGE_PERMISSION")

    def test_stale_watcher_fails_closed_before_quote_logic(self):
        quote = decide_quote(fresh_row(heartbeat_ok=False, watcher_age_seconds=999), now=NOW)

        self.assertFalse(quote["quote_permission"])
        self.assertEqual(quote["reason_code"], "NO_QUOTE_STALE_WATCHER")

    def test_zero_probability_is_valid_fair_value(self):
        quote = decide_quote(
            fresh_row(
                fair_probability=0.0,
                market_mid=0.0005,
                market_yes=0.0005,
                clob_best_bid=0.0,
                clob_best_ask=0.001,
            ),
            now=NOW,
        )

        self.assertNotEqual(quote["reason_code"], "NO_QUOTE_MISSING_FAIR")
        self.assertEqual(quote["fair_probability"], 0.0)

    def test_policy_snapshot_writes_reason_for_each_latest_band(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = root / "snapshots"
            folder = snapshots_root / "highest-temperature-in-atlanta-on-june-14-2026"
            folder.mkdir(parents=True)
            with (folder / "snapshots_long.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "snapshot_id",
                    "captured_at_utc",
                    "event_slug",
                    "model_version",
                    "range_label",
                    "condition_id",
                    "clob_yes_token_id",
                    "bin_kind",
                    "bin_value_c",
                    "model_probability",
                    "market_yes",
                    "best_bid",
                    "best_ask",
                    "market_status",
                ])
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-14T15:59:30+00:00",
                    "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                    "model_version": "candidate",
                    "range_label": "80-81 F",
                    "condition_id": "c1",
                    "clob_yes_token_id": "t1",
                    "bin_kind": "eq",
                    "bin_value_c": "80",
                    "model_probability": "0.51",
                    "market_yes": "0.50",
                    "best_bid": "0.49",
                    "best_ask": "0.51",
                    "market_status": "active",
                })
                writer.writerow({
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-14T15:59:30+00:00",
                    "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                    "model_version": "candidate",
                    "range_label": "82-83 F",
                    "condition_id": "c2",
                    "clob_yes_token_id": "t2",
                    "bin_kind": "eq",
                    "bin_value_c": "82",
                    "model_probability": "0.70",
                    "market_yes": "0.50",
                    "best_bid": "0.49",
                    "best_ask": "0.51",
                    "market_status": "active",
                })
            with (folder / "clob_features_long.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "snapshot_id",
                    "captured_at_utc",
                    "event_slug",
                    "market_id",
                    "range_label",
                    "bin_kind",
                    "bin_value",
                    "bin_value_hi",
                    "clob_token_id",
                    "clob_book_captured_at_utc",
                    "clob_feature_available",
                    "clob_book_age_seconds",
                    "clob_midpoint",
                    "clob_spread",
                    "clob_best_bid",
                    "clob_best_ask",
                    "clob_depth_1pct_total",
                ])
                writer.writeheader()
                for token, label, value, model_mid in [
                    ("t1", "80-81 F", "80", "0.50"),
                    ("t2", "82-83 F", "82", "0.50"),
                ]:
                    writer.writerow({
                        "snapshot_id": "s1",
                        "captured_at_utc": "2026-06-14T15:59:30+00:00",
                        "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                        "market_id": "atlanta",
                        "range_label": label,
                        "bin_kind": "eq",
                        "bin_value": value,
                        "bin_value_hi": str(int(value) + 1),
                        "clob_token_id": token,
                        "clob_book_captured_at_utc": "2026-06-14T15:59:20+00:00",
                        "clob_feature_available": "1.0",
                        "clob_book_age_seconds": "10.0",
                        "clob_midpoint": model_mid,
                        "clob_spread": "0.02",
                        "clob_best_bid": "0.49",
                        "clob_best_ask": "0.51",
                        "clob_depth_1pct_total": "100.0",
                    })
            promotion = root / "promotion.json"
            promotion.write_text(json.dumps({
                "decisions": {
                    "markets": [
                        {
                            "market_id": "atlanta",
                            "action": "KEEP_SHADOW",
                            "verdict": "SHADOW",
                        }
                    ]
                }
            }), encoding="utf-8")
            known_edge = write_known_edge_map(root / "known_edge.json", [{
                "market_id": "atlanta",
                "cutoff": "*",
                "hour_utc": "*",
                "band_distance_bucket": "*",
                "band_type": "*",
                "casebook_taxonomy": "*",
                "regime": "*",
                "source_fresh": "*",
                "book_imbalance_bucket": "*",
                "permission": "harvest_only",
                "reason": "promotion_shadow",
            }])
            status = root / "observation_status.json"
            status.write_text(json.dumps({
                "last_heartbeat": "2026-06-14T15:59:50+00:00",
                "consecutive_errors": 0,
            }), encoding="utf-8")

            payload = run_policy_snapshot(
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                snapshots_root=snapshots_root,
                observation_status_path=status,
                out=root / "quotes_long.csv",
                json_out=root / "quotes.json",
                markets=["atlanta"],
                now=NOW,
            )
            self.assertEqual(payload["row_count"], 2)
            self.assertEqual(payload["live_trade_permission_rows"], 0)
            self.assertTrue(Path(payload["csv_out"]).exists())
            self.assertEqual(payload["reason_counts"]["QUOTE_HARVEST_MID"], 1)
            self.assertEqual(payload["reason_counts"]["NO_QUOTE_DISAGREEMENT_SHADOW"], 1)
            self.assertTrue(payload["known_edge_map"]["exists"])
            self.assertEqual({row["known_edge_permission"] for row in payload["rows"]}, {"harvest_only"})

    def test_policy_snapshot_uses_edge_allowed_map_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = root / "snapshots"
            folder = snapshots_root / "highest-temperature-in-atlanta-on-june-14-2026"
            folder.mkdir(parents=True)
            with (folder / "snapshots_long.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "snapshot_id",
                    "captured_at_utc",
                    "event_slug",
                    "model_version",
                    "range_label",
                    "condition_id",
                    "clob_yes_token_id",
                    "bin_kind",
                    "bin_value_c",
                    "model_probability",
                    "market_yes",
                    "best_bid",
                    "best_ask",
                    "market_status",
                ])
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-14T15:59:30+00:00",
                    "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                    "model_version": "candidate",
                    "range_label": "80-81 F",
                    "condition_id": "c1",
                    "clob_yes_token_id": "t1",
                    "bin_kind": "eq",
                    "bin_value_c": "80",
                    "model_probability": "0.70",
                    "market_yes": "0.50",
                    "best_bid": "0.49",
                    "best_ask": "0.51",
                    "market_status": "active",
                })
            with (folder / "clob_features_long.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "snapshot_id",
                    "captured_at_utc",
                    "event_slug",
                    "market_id",
                    "range_label",
                    "bin_kind",
                    "bin_value",
                    "bin_value_hi",
                    "clob_token_id",
                    "clob_book_captured_at_utc",
                    "clob_book_age_seconds",
                    "clob_midpoint",
                    "clob_spread",
                    "clob_best_bid",
                    "clob_best_ask",
                    "clob_depth_1pct_total",
                ])
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-14T15:59:30+00:00",
                    "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                    "market_id": "atlanta",
                    "range_label": "80-81 F",
                    "bin_kind": "eq",
                    "bin_value": "80",
                    "bin_value_hi": "81",
                    "clob_token_id": "t1",
                    "clob_book_captured_at_utc": "2026-06-14T15:59:20+00:00",
                    "clob_book_age_seconds": "10.0",
                    "clob_midpoint": "0.50",
                    "clob_spread": "0.02",
                    "clob_best_bid": "0.49",
                    "clob_best_ask": "0.51",
                    "clob_depth_1pct_total": "100.0",
                })
            promotion = root / "promotion.json"
            promotion.write_text(json.dumps({
                "decisions": {
                    "markets": [
                        {
                            "market_id": "atlanta",
                            "action": "PROMOTE_CANDIDATE",
                            "verdict": "PASS",
                        }
                    ]
                }
            }), encoding="utf-8")
            known_edge = write_known_edge_map(root / "known_edge.json", [{
                "market_id": "atlanta",
                "cutoff": "*",
                "hour_utc": "*",
                "band_distance_bucket": "*",
                "band_type": "*",
                "casebook_taxonomy": "*",
                "regime": "*",
                "source_fresh": "*",
                "book_imbalance_bucket": "*",
                "permission": "edge_allowed",
                "reason": "live_forward_paper_gate_clear",
            }])
            status = root / "observation_status.json"
            status.write_text(json.dumps({
                "last_heartbeat": "2026-06-14T15:59:50+00:00",
                "consecutive_errors": 0,
            }), encoding="utf-8")

            payload = run_policy_snapshot(
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                snapshots_root=snapshots_root,
                observation_status_path=status,
                out=root / "quotes_long.csv",
                json_out=root / "quotes.json",
                markets=["atlanta"],
                now=NOW,
            )

            self.assertEqual(payload["quote_permission_rows"], 1)
            self.assertEqual(payload["reason_counts"]["QUOTE_EDGE_MODEL"], 1)
            row = payload["rows"][0]
            self.assertTrue(row["known_edge_allowed"])
            self.assertEqual(row["known_edge_permission"], "edge_allowed")
            self.assertTrue(row["known_edge_record_key"])

    def test_policy_snapshot_prefers_source_freshness_gap_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = root / "snapshots"
            folder = snapshots_root / "highest-temperature-in-atlanta-on-june-14-2026"
            folder.mkdir(parents=True)
            with (folder / "snapshots_long.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "snapshot_id",
                    "captured_at_utc",
                    "event_slug",
                    "model_version",
                    "range_label",
                    "condition_id",
                    "clob_yes_token_id",
                    "bin_kind",
                    "bin_value_c",
                    "model_probability",
                    "market_yes",
                    "best_bid",
                    "best_ask",
                    "market_status",
                ])
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-14T15:59:30+00:00",
                    "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                    "model_version": "candidate",
                    "range_label": "80-81 F",
                    "condition_id": "c1",
                    "clob_yes_token_id": "t1",
                    "bin_kind": "eq",
                    "bin_value_c": "80",
                    "model_probability": "0.70",
                    "market_yes": "0.50",
                    "best_bid": "0.49",
                    "best_ask": "0.51",
                    "market_status": "active",
                })
            with (folder / "clob_features_long.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "snapshot_id",
                    "captured_at_utc",
                    "event_slug",
                    "market_id",
                    "range_label",
                    "bin_kind",
                    "bin_value",
                    "bin_value_hi",
                    "clob_token_id",
                    "clob_book_captured_at_utc",
                    "clob_book_age_seconds",
                    "clob_midpoint",
                    "clob_spread",
                    "clob_best_bid",
                    "clob_best_ask",
                    "clob_depth_1pct_total",
                ])
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-14T15:59:30+00:00",
                    "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                    "market_id": "atlanta",
                    "range_label": "80-81 F",
                    "bin_kind": "eq",
                    "bin_value": "80",
                    "bin_value_hi": "81",
                    "clob_token_id": "t1",
                    "clob_book_captured_at_utc": "2026-06-14T15:59:20+00:00",
                    "clob_book_age_seconds": "10.0",
                    "clob_midpoint": "0.50",
                    "clob_spread": "0.02",
                    "clob_best_bid": "0.49",
                    "clob_best_ask": "0.51",
                    "clob_depth_1pct_total": "100.0",
                })
            with (folder / "source_status_long.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "snapshot_id",
                    "source",
                    "ok",
                    "status",
                    "stale",
                ])
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "s1",
                    "source": "wu_history",
                    "ok": "False",
                    "status": "failed",
                    "stale": "False",
                })
                writer.writerow({
                    "snapshot_id": "s1",
                    "source": "metar",
                    "ok": "True",
                    "status": "fresh",
                    "stale": "False",
                })
            promotion = root / "promotion.json"
            promotion.write_text(json.dumps({
                "decisions": {
                    "markets": [
                        {
                            "market_id": "atlanta",
                            "action": "PROMOTE_CANDIDATE",
                            "verdict": "PASS",
                        }
                    ]
                }
            }), encoding="utf-8")
            known_edge = write_known_edge_map(root / "known_edge.json", [
                {
                    "market_id": "atlanta",
                    "cutoff": "*",
                    "hour_utc": "*",
                    "band_distance_bucket": "*",
                    "band_type": "*",
                    "casebook_taxonomy": "*",
                    "regime": "*",
                    "source_fresh": "*",
                    "source_freshness_state": "*",
                    "book_imbalance_bucket": "*",
                    "permission": "edge_allowed",
                    "reason": "live_forward_paper_gate_clear",
                },
                {
                    "market_id": "*",
                    "cutoff": "*",
                    "hour_utc": "*",
                    "band_distance_bucket": "*",
                    "band_type": "*",
                    "casebook_taxonomy": "*",
                    "regime": "*",
                    "source_fresh": "*",
                    "source_freshness_state": "failed:wu_history",
                    "book_imbalance_bucket": "*",
                    "permission": "harvest_only",
                    "reason": "source_freshness_model_gap",
                },
            ])
            status = root / "observation_status.json"
            status.write_text(json.dumps({
                "last_heartbeat": "2026-06-14T15:59:50+00:00",
                "consecutive_errors": 0,
            }), encoding="utf-8")

            payload = run_policy_snapshot(
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                snapshots_root=snapshots_root,
                observation_status_path=status,
                out=root / "quotes_long.csv",
                json_out=root / "quotes.json",
                markets=["atlanta"],
                now=NOW,
            )

            row = payload["rows"][0]
            self.assertEqual(row["source_freshness_state"], "failed:wu_history")
            self.assertEqual(row["known_edge_permission"], "harvest_only")
            self.assertEqual(row["known_edge_reason"], "source_freshness_model_gap")
            self.assertFalse(row["known_edge_allowed"])
            self.assertNotEqual(row["reason_code"], "QUOTE_EDGE_MODEL")


if __name__ == "__main__":
    unittest.main()
