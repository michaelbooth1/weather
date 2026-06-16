import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from mm_paper import build_known_edge_map, build_paper_payload, write_outputs


EVENT = "highest-temperature-in-atlanta-on-june-14-2026"
TARGET_DATE = "2026-06-14"


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_promotion(path):
    payload = {
        "decisions": {
            "verdict": "PARTIAL_PASS",
            "action_counts": {
                "PROMOTE_CANDIDATE": 1,
                "KEEP_SHADOW": 1,
                "BLOCK_CANDIDATE": 1,
            },
            "markets": [
                {
                    "market_id": "atlanta",
                    "action": "PROMOTE_CANDIDATE",
                    "verdict": "PASS",
                    "metrics": {
                        "candidate_brier": 0.03,
                        "market_brier": 0.04,
                        "delta_vs_market": -0.01,
                    },
                },
                {
                    "market_id": "chicago",
                    "action": "KEEP_SHADOW",
                    "verdict": "SHADOW",
                    "metrics": {
                        "candidate_brier": 0.05,
                        "market_brier": 0.04,
                        "delta_vs_market": 0.01,
                    },
                },
                {
                    "market_id": "san-francisco",
                    "action": "BLOCK_CANDIDATE",
                    "verdict": "BLOCK",
                    "metrics": {
                        "candidate_brier": 0.06,
                        "market_brier": 0.04,
                        "delta_vs_market": 0.02,
                    },
                },
            ],
        },
        "candidate": {
            "slices": {
                "by_source_freshness": [
                    {
                        "group": "failed:wu_history",
                        "n": 42,
                        "candidate_brier": 0.08,
                        "current_brier": 0.10,
                        "market_brier": 0.05,
                        "delta_vs_current": -0.02,
                        "delta_vs_market": 0.03,
                    },
                    {
                        "group": "failed:local_history",
                        "n": 4,
                        "candidate_brier": 0.03,
                        "current_brier": 0.05,
                        "market_brier": 0.06,
                        "delta_vs_current": -0.02,
                        "delta_vs_market": -0.03,
                    },
                    {
                        "group": "failed:metar",
                        "n": 3,
                        "candidate_brier": 0.05,
                        "current_brier": 0.05,
                        "market_brier": 0.04,
                        "delta_vs_current": 0.0,
                        "delta_vs_market": 0.01,
                    },
                ]
            }
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_casebook(path):
    payload = {
        "cases": [
            {
                "case_id": "case-atlanta-80",
                "event_slug": EVENT,
                "market_id": "atlanta",
                "range_label": "80-81 F",
                "start_time_utc": "2026-06-14T16:00:00+00:00",
                "end_time_utc": "2026-06-14T16:05:00+00:00",
                "taxonomy": "market_lead",
            }
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_run_fixture(root):
    runs_root = root / "mm_runs"
    run_folder = runs_root / TARGET_DATE / "paper-run"
    run_folder.mkdir(parents=True)
    run_config = {
        "run_id": "paper-run",
        "mode": "paper-live-forward",
        "target_date": TARGET_DATE,
        "policy_hash": "locked-policy",
    }
    (run_folder / "run_config.json").write_text(json.dumps(run_config), encoding="utf-8")
    quote_row = {
        "run_id": "paper-run",
        "target_date": TARGET_DATE,
        "run_mode": "paper-live-forward",
        "generated_at_utc": "2026-06-14T16:00:00+00:00",
        "captured_at_utc": "2026-06-14T15:59:30+00:00",
        "policy_hash": "locked-policy",
        "quote_permission": "True",
        "market_id": "atlanta",
        "event_slug": EVENT,
        "range_label": "80-81 F",
        "bin_kind": "eq",
        "bin_value": "80",
        "bin_value_hi": "81",
        "clob_token_id": "token-80",
        "fair_probability": "0.50",
        "market_mid": "0.50",
        "bid_price": "0.49",
        "bid_size": "5",
        "ask_price": "0.51",
        "ask_size": "5",
        "regime": "harvest",
        "source_fresh": "True",
        "book_imbalance_1pct": "0.10",
        "min_order_size": "1",
        "reason_code": "QUOTE_HARVEST_MID",
    }
    write_csv(run_folder / "quote_intents_long.csv", list(quote_row.keys()), [quote_row])
    return runs_root, run_folder


def write_minimal_run(root, run_id, schema_version, target_date, gate_counts=True):
    runs_root = root / "mm_runs"
    run_folder = runs_root / target_date / run_id
    run_folder.mkdir(parents=True)
    run_config = {
        "run_id": run_id,
        "mode": "paper-live-forward",
        "target_date": target_date,
        "policy_hash": f"policy-{run_id}",
        "schema_version": schema_version,
    }
    (run_folder / "run_config.json").write_text(json.dumps(run_config), encoding="utf-8")
    summary = {
        "schema_version": schema_version,
        "run_id": run_id,
        "mode": "paper-live-forward",
        "target_date": target_date,
        "policy_hash": f"policy-{run_id}",
        "preflight_status": "PASS" if gate_counts else "STALE",
        "preflight_remediation": {
            "counts_toward_live_forward_gate": gate_counts,
        },
    }
    (run_folder / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    quote_row = {
        "run_id": run_id,
        "target_date": target_date,
        "run_mode": "paper-live-forward",
        "generated_at_utc": f"{target_date}T16:00:00+00:00",
        "captured_at_utc": f"{target_date}T15:59:30+00:00",
        "policy_hash": f"policy-{run_id}",
        "quote_permission": "True",
        "market_id": "atlanta",
        "event_slug": EVENT,
        "range_label": "80-81 F",
        "bin_kind": "eq",
        "bin_value": "80",
        "bin_value_hi": "81",
        "clob_token_id": f"token-{run_id}",
        "fair_probability": "0.50",
        "market_mid": "0.50",
        "bid_price": "0.49",
        "bid_size": "5",
        "ask_price": "0.51",
        "ask_size": "5",
        "regime": "harvest",
        "source_fresh": "True",
        "book_imbalance_1pct": "0.10",
        "min_order_size": "1",
        "reason_code": "QUOTE_HARVEST_MID",
    }
    write_csv(run_folder / "quote_intents_long.csv", list(quote_row.keys()), [quote_row])
    return runs_root, run_folder


def write_snapshot_fixture(root):
    snapshots_root = root / "snapshots"
    folder = snapshots_root / EVENT
    folder.mkdir(parents=True)
    trades = [
        {
            "trade_time_utc": "2026-06-14T16:00:10+00:00",
            "clob_token_id": "token-80",
            "price": "0.49",
            "size": "10",
            "side": "SELL",
        },
        {
            "trade_time_utc": "2026-06-14T16:00:20+00:00",
            "clob_token_id": "token-80",
            "price": "0.48",
            "size": "3",
            "side": "SELL",
        },
        {
            "trade_time_utc": "2026-06-14T16:00:30+00:00",
            "clob_token_id": "token-80",
            "price": "0.47",
            "size": "",
            "side": "SELL",
        },
    ]
    write_csv(folder / "trades_long.csv", list(trades[0].keys()), trades)
    book_rows = [
        {
            "captured_at_utc": "2026-06-14T15:59:50+00:00",
            "event_slug": EVENT,
            "market_id": "atlanta",
            "range_label": "80-81 F",
            "bin_kind": "eq",
            "bin_value": "80",
            "bin_value_hi": "81",
            "clob_token_id": "token-80",
            "best_bid": "0.49",
            "best_ask": "0.51",
            "midpoint": "0.50",
            "last_trade_price": "",
            "bid_size_at_best": "10",
            "ask_size_at_best": "10",
            "bid_depth_1pct": "10",
            "ask_depth_1pct": "10",
            "tick_size": "0.001",
        },
        {
            "captured_at_utc": "2026-06-14T16:00:15+00:00",
            "event_slug": EVENT,
            "market_id": "atlanta",
            "range_label": "80-81 F",
            "bin_kind": "eq",
            "bin_value": "80",
            "bin_value_hi": "81",
            "clob_token_id": "token-80",
            "best_bid": "0.49",
            "best_ask": "0.51",
            "midpoint": "0.50",
            "last_trade_price": "",
            "bid_size_at_best": "5",
            "ask_size_at_best": "10",
            "bid_depth_1pct": "5",
            "ask_depth_1pct": "10",
            "tick_size": "0.001",
        },
        {
            "captured_at_utc": "2026-06-14T16:00:25+00:00",
            "event_slug": EVENT,
            "market_id": "atlanta",
            "range_label": "80-81 F",
            "bin_kind": "eq",
            "bin_value": "80",
            "bin_value_hi": "81",
            "clob_token_id": "token-80",
            "best_bid": "0.48",
            "best_ask": "0.51",
            "midpoint": "0.505",
            "last_trade_price": "",
            "bid_size_at_best": "5",
            "ask_size_at_best": "10",
            "bid_depth_1pct": "5",
            "ask_depth_1pct": "10",
            "tick_size": "0.001",
        },
    ]
    write_csv(folder / "order_books_summary.csv", list(book_rows[0].keys()), book_rows)
    marks = [
        {
            "point_time_utc": "2026-06-14T16:00:50+00:00",
            "clob_token_id": "token-80",
            "price": "0.53",
        },
        {
            "point_time_utc": "2026-06-14T16:01:20+00:00",
            "clob_token_id": "token-80",
            "price": "0.53",
        },
        {
            "point_time_utc": "2026-06-14T16:05:30+00:00",
            "clob_token_id": "token-80",
            "price": "0.54",
        },
        {
            "point_time_utc": "2026-06-14T16:30:30+00:00",
            "clob_token_id": "token-80",
            "price": "0.54",
        },
    ]
    write_csv(folder / "price_history.csv", list(marks[0].keys()), marks)
    settlement = {
        "event_slug": EVENT,
        "market_id": "atlanta",
        "settlement_bucket": 80,
        "winning_band": "80-81 F",
        "quality_grade": "complete",
    }
    (folder / "settlement.json").write_text(json.dumps(settlement), encoding="utf-8")
    return snapshots_root


class TestMMPaper(unittest.TestCase):
    def test_conservative_fills_queue_markouts_incentives_and_known_edge_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root, run_folder = write_run_fixture(root)
            snapshots_root = write_snapshot_fixture(root)
            backtest_root = root / "backtest"
            promotion = backtest_root / "promotion.json"
            casebook = backtest_root / "casebook.json"
            write_promotion(promotion)
            write_casebook(casebook)

            config = {
                "quote_ttl_seconds": 120.0,
                "reward_campaign_pool_usdc": 100.0,
                "reward_competitor_q": 50.0,
                "reward_min_payout_usdc": 0.0,
            }
            payload = build_paper_payload(
                runs_root=runs_root,
                snapshots_root=snapshots_root,
                backtest_root=backtest_root,
                run_folders=[run_folder],
                casebook_path=casebook,
                promotion_refresh=promotion,
                config=config,
                now="2026-06-14T17:00:00+00:00",
            )
            payload, known_edge = write_outputs(
                payload,
                json_out=backtest_root / "mm_paper_report.json",
                report_out=backtest_root / "mm_paper_report.md",
                fills_out=backtest_root / "mm_paper_fills_long.csv",
                known_edge_out=backtest_root / "mm_known_edge_map.json",
                known_edge_report_out=backtest_root / "mm_known_edge_map.md",
                promotion_refresh=promotion,
            )

            self.assertEqual(payload["summary"]["conservative_fills"], 1)
            self.assertEqual(payload["summary"]["trade_evidence_gaps"]["missing_size_trade_rows"], 1)
            fill = payload["fills"][0]
            self.assertEqual(fill["side"], "YES_BID")
            self.assertEqual(float(fill["fill_price"]), 0.49)
            self.assertEqual(float(fill["fill_size"]), 3.0)
            self.assertEqual(float(fill["through_trade_price"]), 0.48)
            self.assertGreater(float(fill["markout_30m_per_share"]), 0.0)
            self.assertEqual(float(fill["settlement_outcome"]), 1.0)
            self.assertEqual(fill["casebook_taxonomy"], "market_lead")
            self.assertGreater(float(fill["maker_rebate_estimate_usdc"]), 0.0)
            self.assertGreater(float(fill["liquidity_reward_estimate_usdc"]), 0.0)
            self.assertGreater(float(fill["flattening_fee_estimate_usdc"]), 0.0)
            self.assertGreater(float(fill["net_pnl_after_fees_incentives_usdc"]), 0.0)

            bid_queue = [row for row in payload["queue_companion"] if row["leg_id"].endswith("YES_BID")][0]
            self.assertEqual(bid_queue["status"], "estimated_full_fill")
            self.assertEqual(float(bid_queue["estimated_fill_size"]), 5.0)

            files = payload["outputs"]
            self.assertTrue(Path(files["json"]).exists())
            self.assertTrue(Path(files["report"]).exists())
            self.assertTrue(Path(files["fills_csv"]).exists())
            self.assertTrue(Path(files["known_edge_json"]).exists())
            csv_rows = read_csv(files["fills_csv"])
            self.assertEqual(len(csv_rows), 1)

            permissions = {(row["market_id"], row["permission"]) for row in known_edge["records"]}
            self.assertIn(("atlanta", "edge_research"), permissions)
            self.assertIn(("chicago", "harvest_only"), permissions)
            self.assertIn(("san-francisco", "no_quote"), permissions)

    def test_no_runs_writes_empty_report_and_fail_closed_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest_root = root / "backtest"
            promotion = backtest_root / "promotion.json"
            write_promotion(promotion)

            payload = build_paper_payload(
                runs_root=root / "missing_mm_runs",
                snapshots_root=root / "snapshots",
                backtest_root=backtest_root,
                promotion_refresh=promotion,
                config={"quote_ttl_seconds": 120.0},
                now="2026-06-14T17:00:00+00:00",
            )
            known_edge = build_known_edge_map(payload, promotion_refresh=promotion)

            self.assertEqual(payload["summary"]["quote_rows"], 0)
            self.assertEqual(payload["summary"]["conservative_fills"], 0)
            permission_by_market = {row["market_id"]: row["permission"] for row in known_edge["records"]}
            self.assertEqual(permission_by_market["atlanta"], "harvest_only")
            self.assertEqual(permission_by_market["chicago"], "harvest_only")
            self.assertEqual(permission_by_market["san-francisco"], "no_quote")
            source_records = [
                row for row in known_edge["records"]
                if row.get("reason") == "source_freshness_model_gap"
            ]
            self.assertEqual(
                {row["source_freshness_state"] for row in source_records},
                {"failed:wu_history", "failed:metar"},
            )
            self.assertTrue(all(row["reason"] == "source_freshness_model_gap" for row in source_records))
            self.assertEqual(
                known_edge["active_model_gap_cells"][0]["source_freshness_state"],
                "failed:wu_history",
            )
            success_records = [
                row for row in known_edge["records"]
                if row.get("reason") == "dynamic_source_state_replay_gate_clear"
            ]
            self.assertEqual(
                {row["source_freshness_state"] for row in success_records},
                {"failed:wu_history", "failed:local_history"},
            )
            self.assertNotIn(
                "failed:metar",
                {row["source_freshness_state"] for row in success_records},
            )
            self.assertTrue(all(row["permission"] == "edge_research" for row in success_records))
            self.assertTrue(all(row["uses_market_features"] is False for row in success_records))

    def test_clob_overlay_gate_feeds_market_informed_known_edge_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            promotion = root / "backtest" / "promotion.json"
            write_promotion(promotion)
            payload = json.loads(promotion.read_text(encoding="utf-8"))
            payload["candidate"]["microstructure"] = {
                "gate": {
                    "schema_version": "clob_microstructure_taxonomy_gate_v0.1",
                    "policy": "target_taxonomy_replay_allowlist",
                    "min_rows": 25,
                    "max_delta_vs_candidate": 0.0,
                    "max_delta_vs_market": 0.0,
                    "max_logloss_delta_vs_candidate": 0.0,
                    "max_ece": 0.12,
                    "max_overconfident_error_rate": 0.25,
                    "decisions": [
                        {
                            "taxonomy": "market_lead",
                            "allowed": True,
                            "rows": 75,
                            "micro_brier": 0.00001,
                            "candidate_brier": 0.0136,
                            "market_brier": 0.0007,
                            "micro_logloss": 0.0028,
                            "candidate_logloss": 0.0811,
                            "micro_ece": 0.0028,
                            "micro_overconfident_error_rate": 0.0,
                            "delta_vs_candidate": -0.0136,
                            "delta_vs_market": -0.0006,
                            "reason": "replay-proven improvement",
                        },
                        {
                            "taxonomy": "market_overreaction",
                            "allowed": False,
                            "rows": 645,
                            "delta_vs_candidate": 0.0718,
                            "reason": "candidate regression",
                        },
                    ],
                }
            }
            promotion.write_text(json.dumps(payload), encoding="utf-8")

            known_edge = build_known_edge_map(
                {
                    "schema_version": "mm_paper_v0.1",
                    "summary": {"anti_overfit": {"policy_hashes": ["policy-1"]}},
                },
                promotion_refresh=promotion,
            )

        clob_records = [
            row for row in known_edge["records"]
            if row.get("base_permission") == "CLOB_OVERLAY_MARKET_INFORMED"
        ]
        self.assertEqual(len(clob_records), 1)
        record = clob_records[0]
        self.assertEqual(record["casebook_taxonomy"], "market_lead")
        self.assertEqual(record["permission"], "edge_research")
        self.assertEqual(record["source_fresh"], "*")
        self.assertTrue(record["uses_market_features"])
        self.assertTrue(record["market_informed"])
        self.assertTrue(record["quote_time_only"])
        self.assertFalse(record["weather_model_promotion_evidence"])
        self.assertEqual(record["requires_policy_hash"], ["policy-1"])
        self.assertEqual(record["clob_overlay_gate"]["max_logloss_delta_vs_candidate"], 0.0)
        self.assertTrue(known_edge["summary"]["clob_overlay_quote_guardrails_present"])
        self.assertEqual(known_edge["summary"]["clob_overlay_allowed_taxonomy_count"], 1)
        self.assertEqual(known_edge["summary"]["clob_overlay_blocked_taxonomy_count"], 1)

        del payload["candidate"]["microstructure"]["gate"]["max_logloss_delta_vs_candidate"]
        with tempfile.TemporaryDirectory() as tmp:
            stale_promotion = Path(tmp) / "backtest" / "promotion.json"
            stale_promotion.parent.mkdir(parents=True)
            stale_promotion.write_text(json.dumps(payload), encoding="utf-8")
            stale_gate = build_known_edge_map(
                {
                    "schema_version": "mm_paper_v0.1",
                    "summary": {"anti_overfit": {"policy_hashes": ["policy-1"]}},
                },
                promotion_refresh=stale_promotion,
            )
        self.assertFalse(any(
            row.get("base_permission") == "CLOB_OVERLAY_MARKET_INFORMED"
            for row in stale_gate["records"]
        ))
        self.assertFalse(stale_gate["summary"]["clob_overlay_quote_guardrails_present"])

    def test_event_gate_score_tracks_suppressed_opportunity_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root = root / "mm_runs"
            run_folder = runs_root / TARGET_DATE / "event-gate-run"
            run_folder.mkdir(parents=True)
            (run_folder / "run_config.json").write_text(json.dumps({
                "schema_version": "mm_run_v0.2",
                "run_id": "event-gate-run",
                "mode": "paper-live-forward",
                "target_date": TARGET_DATE,
                "policy_hash": "locked-policy",
            }), encoding="utf-8")
            (run_folder / "run_summary.json").write_text(json.dumps({
                "schema_version": "mm_run_v0.2",
                "run_id": "event-gate-run",
                "mode": "paper-live-forward",
                "target_date": TARGET_DATE,
                "policy_hash": "locked-policy",
                "preflight_status": "PASS",
            }), encoding="utf-8")
            quote_row = {
                "run_id": "event-gate-run",
                "target_date": TARGET_DATE,
                "run_mode": "paper-live-forward",
                "generated_at_utc": "2026-06-14T15:52:00+00:00",
                "captured_at_utc": "2026-06-14T15:51:30+00:00",
                "policy_hash": "locked-policy",
                "quote_permission": "False",
                "reason_code": "NO_QUOTE_INFORMATION_EVENT",
                "market_id": "atlanta",
                "event_slug": EVENT,
                "range_label": "80-81 F",
                "fair_probability": "0.54",
                "market_mid": "0.50",
                "edge": "0.04",
                "quote_size": "5",
                "event_gate_status": "PULL",
                "event_gate_action": "suppress",
                "event_gate_event_class": "metar_print_window",
                "event_gate_reason_code": "INFO_EVENT_METAR_PRINT",
            }
            write_csv(run_folder / "quote_intents_long.csv", list(quote_row.keys()), [quote_row])

            payload = build_paper_payload(
                runs_root=runs_root,
                snapshots_root=root / "snapshots",
                backtest_root=root / "backtest",
                run_folders=[run_folder],
                config={"quote_ttl_seconds": 120.0},
                now="2026-06-14T17:00:00+00:00",
            )
            payload, _known_edge = write_outputs(
                payload,
                json_out=root / "backtest" / "mm_paper_report.json",
                report_out=root / "backtest" / "mm_paper_report.md",
                fills_out=root / "backtest" / "mm_paper_fills_long.csv",
                known_edge_out=root / "backtest" / "mm_known_edge_map.json",
                known_edge_report_out=root / "backtest" / "mm_known_edge_map.md",
            )

            score = payload["summary"]["event_gate_score"]
            self.assertEqual(score["suppressed_rows"], 1)
            self.assertAlmostEqual(score["suppressed_opportunity_cost_usdc"], 0.2)
            self.assertEqual(score["narrowing_gate"], "NEEDS_MARKOUT_EVIDENCE")
            report = (root / "backtest" / "mm_paper_report.md").read_text(encoding="utf-8")
            self.assertIn("## Information Event Gate", report)

    def test_clob_recon_summary_feeds_paper_report_and_known_edge_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recon = root / "backtest" / "clob_book_recon.json"
            recon.parent.mkdir(parents=True)
            recon.write_text(json.dumps({
                "schema_version": "clob_book_recon_v0.1",
                "summary": {
                    "book_rows": 2,
                    "slice_rows": 1,
                    "mean_reward_qualifying_size": 80.0,
                    "mean_spread": 0.02,
                    "mean_passive_markout_300s": -0.01,
                    "policy_parameter_suggestions": {"quote_size": 2.0},
                },
                "policy_parameter_suggestions": {"quote_size": 2.0},
                "slices": [
                    {
                        "market_id": "atlanta",
                        "hour_utc": "15:00Z",
                        "side": "YES_BID",
                        "recommended_permission": "harvest_only",
                        "permission_reason": "passive_flow_toxic",
                    }
                ],
            }), encoding="utf-8")

            payload = build_paper_payload(
                runs_root=root / "missing_mm_runs",
                snapshots_root=root / "snapshots",
                backtest_root=root / "backtest",
                clob_recon_path=recon,
                now="2026-06-14T17:00:00+00:00",
            )
            payload, known_edge = write_outputs(
                payload,
                json_out=root / "backtest" / "mm_paper_report.json",
                report_out=root / "backtest" / "mm_paper_report.md",
                fills_out=root / "backtest" / "mm_paper_fills_long.csv",
                known_edge_out=root / "backtest" / "mm_known_edge_map.json",
                known_edge_report_out=root / "backtest" / "mm_known_edge_map.md",
            )

            self.assertEqual(payload["summary"]["clob_recon"]["slice_rows"], 1)
            report = (root / "backtest" / "mm_paper_report.md").read_text(encoding="utf-8")
            self.assertIn("## CLOB Recon", report)
            self.assertTrue(any(row.get("clob_recon_evidence") for row in known_edge["records"]))

    def test_incompatible_schema_is_quarantined_and_non_countable_run_does_not_lock_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root, _old_run = write_minimal_run(root, "old-v1", "mm_run_v0.1", TARGET_DATE)
            _runs_root, current_run = write_minimal_run(root, "current-v2", "mm_run_v0.2", "2026-06-15", gate_counts=False)

            payload = build_paper_payload(
                runs_root=runs_root,
                snapshots_root=root / "snapshots",
                backtest_root=root / "backtest",
                run_folders=[runs_root / TARGET_DATE / "old-v1", current_run],
                config={"quote_ttl_seconds": 120.0},
                now="2026-06-15T17:00:00+00:00",
            )

            self.assertEqual(payload["summary"]["candidate_run_folders"], 2)
            self.assertEqual(payload["summary"]["excluded_run_folders"], 1)
            self.assertEqual(payload["summary"]["run_folders"], 1)
            self.assertEqual(payload["summary"]["quote_rows"], 1)
            self.assertEqual(payload["excluded_run_folders"][0]["schema_version"], "mm_run_v0.1")
            self.assertEqual(payload["summary"]["anti_overfit"]["live_forward_days"], [])
            current_key = str(current_run)
            self.assertFalse(payload["run_folder_eligibility"][current_key]["live_forward_gate_counts"])


if __name__ == "__main__":
    unittest.main()
