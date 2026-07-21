import csv
import gc
import json
import os
import sys
import tempfile
import tracemalloc
import unittest
from datetime import date, timedelta
from pathlib import Path
from weather.market import exchange_economics
from weather.market.live_forward_gate import build_live_forward_gate
from weather.market.market_making_run_constants import RUN_QUOTE_COLUMNS
from weather.market.mm_paper import (
    build_known_edge_map,
    build_paper_payload,
    maker_paper_score_freshness_from_report,
    model_variant_clustered_promotion_gate,
    quote_blocker_diagnostics,
    run_folder_eligibility,
    write_outputs,
)
from weather.market.mm_paper_scoring import load_casebook_index, write_json as write_scoring_json
from weather.market.mm_scoring_projection import (
    resolve_run_scoring_inputs,
    write_run_scoring_projections,
)


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


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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


def test_casebook_index_streams_and_filters_event_slugs():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "casebook.json"
        payload = {
            "cases": [
                {
                    "case_id": "case-keep",
                    "event_slug": EVENT,
                    "market_id": "atlanta",
                    "range_label": "80-81 F",
                    "start_time_utc": "2026-06-14T16:00:00+00:00",
                    "end_time_utc": "2026-06-14T16:05:00+00:00",
                    "taxonomy": "market_lead",
                    "nested": {"event_slug": "not-the-filter-key", "note": "brace { in string }"},
                },
                {
                    "case_id": "case-drop",
                    "event_slug": "highest-temperature-in-chicago-on-june-14-2026",
                    "market_id": "chicago",
                    "range_label": "80-81 F",
                    "start_time_utc": "2026-06-14T16:00:00+00:00",
                    "end_time_utc": "2026-06-14T16:05:00+00:00",
                    "taxonomy": "other_market",
                },
            ],
            "config": {"unrelated": True},
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        filtered = load_casebook_index(path, event_slugs={EVENT})
        unfiltered = load_casebook_index(path)

    self_key = (EVENT, "atlanta", "80-81 F")
    other_key = ("highest-temperature-in-chicago-on-june-14-2026", "chicago", "80-81 F")
    assert filtered[self_key][0]["case_id"] == "case-keep"
    assert other_key not in filtered
    assert unfiltered[other_key][0]["case_id"] == "case-drop"


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
        "live_trade_permission": "False",
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


def write_no_quote_run_fixture(root, run_index, row_count):
    target_date = (date(2026, 4, 1) + timedelta(days=run_index)).isoformat()
    run_id = f"stream-run-{run_index:03d}"
    run_folder = root / "mm_runs" / target_date / run_id
    run_folder.mkdir(parents=True)
    run_config = {
        "run_id": run_id,
        "mode": "paper-live-forward",
        "target_date": target_date,
        "policy_hash": "locked-policy",
        "schema_version": "mm_run_v0.2",
    }
    (run_folder / "run_config.json").write_text(json.dumps(run_config), encoding="utf-8")
    rows = [
        {
            "run_id": run_id,
            "target_date": target_date,
            "run_mode": "paper-live-forward",
            "generated_at_utc": f"{target_date}T16:{row_index % 60:02d}:00+00:00",
            "captured_at_utc": f"{target_date}T15:59:30+00:00",
            "policy_hash": "locked-policy",
            "quote_permission": "True" if row_index < 32 else "False",
            "live_trade_permission": "False",
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
            "reason_code": "QUOTE_HARVEST_MID" if row_index < 32 else "NO_QUOTE_TEST",
        }
        for row_index in range(row_count)
    ]
    write_csv(run_folder / "quote_intents_long.csv", list(rows[0].keys()), rows)
    variant_rows = [
        {
            **row,
            "model_variant_id": "candidate_shadow",
            "model_variant_family": "test",
            "model_variant_role": "shadow",
            "model_variant_counterfactual": "True",
        }
        for row in rows
    ]
    write_csv(
        run_folder / "model_variant_quote_intents_long.csv",
        list(variant_rows[0].keys()),
        variant_rows,
    )
    return run_folder


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


def mark_active_day(run_folder, counts=True):
    path = Path(run_folder) / "run_summary.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["evidence_mode"] = "active_day_live_forward"
    payload["counts_toward_live_forward_gate"] = counts
    payload["generated_at_utc"] = f"{payload['target_date']}T20:00:00+00:00"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


LIVE_FORWARD_MARKETS = [
    "atlanta",
    "austin",
    "chicago",
    "denver",
    "houston",
    "las-vegas",
    "los-angeles",
    "miami",
    "nyc",
    "philadelphia",
    "san-francisco",
    "seattle",
]


def write_live_forward_gate(run_folder, run_id, target_date, stale_market="nyc"):
    def gate(name, ok=True, severity="pass", detail="ok"):
        return {"name": name, "ok": ok, "severity": severity, "detail": detail}

    markets = []
    for market_id in LIVE_FORWARD_MARKETS:
        stale = market_id == stale_market
        markets.append({
            "market_id": market_id,
            "city": market_id.title(),
            "event_slug": f"highest-temperature-in-{market_id}-on-june-17-2026",
            "target_date": target_date,
            "status": "STALE" if stale else "PASS",
            "latest_capture_utc": "2026-06-17T15:58:00+00:00",
            "source_status_latest_utc": "2026-06-17T15:58:00+00:00",
            "model_age_seconds": 600.0 if stale else 10.0,
            "book_audit": {
                "last_capture_utc": "2026-06-17T15:59:00+00:00",
                "trailing_age_seconds": 5.0,
            },
            "gates": [
                gate("active_event"),
                gate("event_metadata_validation"),
                gate("snapshot_model_rows"),
                gate(
                    "model_freshness",
                    ok=not stale,
                    severity="stale" if stale else "pass",
                    detail="model row is stale" if stale else "ok",
                ),
                gate("source_status_rows"),
                gate("source_status_fresh"),
                gate("clob_tokens"),
                gate("clob_books"),
                gate("clob_features"),
                gate("clob_freshness"),
                gate("reward_metadata"),
            ],
        })
    preflight = {
        "run_id": run_id,
        "target_date": target_date,
        "mode": "paper-live-forward",
        "generated_at_utc": "2026-06-17T16:00:00+00:00",
        "markets": markets,
    }
    payload = build_live_forward_gate(
        preflight,
        policy_config={"max_model_age_seconds": 60, "max_book_age_seconds": 60},
        now="2026-06-17T16:00:00+00:00",
    )
    (run_folder / "live_forward_gate.json").write_text(json.dumps(payload), encoding="utf-8")
    return payload


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
    def test_model_variant_clustered_gate_blocks_many_rows_from_one_market_day(self):
        quote_rows = []
        for _index in range(40):
            quote_rows.append({
                "target_date": "2026-06-14",
                "market_id": "atlanta",
                "model_variant_id": "served_current",
                "policy_hash": "locked-policy",
                "quote_permission": "True",
            })
            quote_rows.append({
                "target_date": "2026-06-14",
                "market_id": "atlanta",
                "model_variant_id": "candidate_shadow",
                "policy_hash": "locked-policy",
                "quote_permission": "True",
            })
        gate = model_variant_clustered_promotion_gate(
            quote_rows,
            [],
            [],
            [],
            config={
                "model_variant_promotion_min_market_day_clusters": 3,
                "model_variant_promotion_min_target_days": 2,
                "model_variant_promotion_min_markets": 2,
                "model_variant_promotion_bootstrap_iterations": 100,
            },
        )
        candidate = [
            row for row in gate["pairs"]
            if row["model_variant_id"] == "candidate_shadow"
        ][0]

        self.assertEqual(gate["status"], "BLOCK")
        self.assertEqual(candidate["cluster_count"], 1)
        self.assertEqual(candidate["quote_rows"], 40)
        self.assertIn("min_market_day_clusters", candidate["failed_gates"])
        self.assertIn("min_independent_target_days", candidate["failed_gates"])
        self.assertIn("min_independent_markets", candidate["failed_gates"])

    def test_model_variant_clustered_gate_can_pass_paired_market_day_delta(self):
        quote_rows = []
        legs = []
        fills = []
        clusters = [
            ("2026-06-14", "atlanta"),
            ("2026-06-15", "atlanta"),
            ("2026-06-16", "dallas"),
        ]
        for index, (target_date, market_id) in enumerate(clusters):
            for variant_id, net in [("served_current", 0.0), ("candidate_shadow", 1.0)]:
                leg_id = f"{variant_id}-{index}"
                quote_rows.append({
                    "target_date": target_date,
                    "market_id": market_id,
                    "model_variant_id": variant_id,
                    "policy_hash": "locked-policy",
                    "quote_permission": "True",
                })
                legs.append({
                    "target_date": target_date,
                    "market_id": market_id,
                    "model_variant_id": variant_id,
                    "policy_hash": "locked-policy",
                    "leg_id": leg_id,
                    "quote_size": 10,
                })
                fills.append({
                    "target_date": target_date,
                    "market_id": market_id,
                    "model_variant_id": variant_id,
                    "policy_hash": "locked-policy",
                    "fill_size": 1,
                    "net_pnl_after_fees_incentives_usdc": net,
                    "settlement_pnl_usdc": net,
                    "adverse_selection_30m_usdc": net,
                })
        gate = model_variant_clustered_promotion_gate(
            quote_rows,
            legs,
            fills,
            [],
            config={
                "model_variant_promotion_min_market_day_clusters": 3,
                "model_variant_promotion_min_target_days": 3,
                "model_variant_promotion_min_markets": 2,
                "model_variant_promotion_bootstrap_iterations": 100,
            },
        )
        candidate = [
            row for row in gate["pairs"]
            if row["model_variant_id"] == "candidate_shadow"
        ][0]
        delta_net = candidate["delta_vs_served_current_cluster_metrics"][
            "net_pnl_after_fees_incentives_usdc"
        ]

        self.assertEqual(gate["status"], "PASS")
        self.assertEqual(candidate["status"], "PASS")
        self.assertEqual(candidate["cluster_count"], 3)
        self.assertEqual(candidate["independent_target_day_count"], 3)
        self.assertEqual(candidate["independent_market_count"], 2)
        self.assertGreater(delta_net["mean_lower"], 0.0)

    def test_paper_score_freshness_passes_when_report_covers_latest_active_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root, old_run = write_minimal_run(root, "old-active", "mm_run_v0.2", "2026-06-18")
            _runs_root, new_run = write_minimal_run(root, "new-active", "mm_run_v0.2", "2026-06-19")
            mark_active_day(old_run)
            mark_active_day(new_run)

            payload = build_paper_payload(
                runs_root=runs_root,
                snapshots_root=root / "snapshots",
                backtest_root=root / "backtest",
            )
            payload, _known = write_outputs(
                payload,
                json_out=root / "backtest" / "mm_paper_report.json",
                report_out=root / "backtest" / "mm_paper_report.md",
                fills_out=root / "backtest" / "mm_paper_fills_long.csv",
                known_edge_out=root / "backtest" / "mm_known_edge_map.json",
                known_edge_report_out=root / "backtest" / "mm_known_edge_map.md",
            )
            report = (root / "backtest" / "mm_paper_report.md").read_text(encoding="utf-8")

        freshness = payload["summary"]["paper_score_freshness"]
        self.assertEqual(freshness["status"], "PASS")
        self.assertEqual(freshness["latest_completed_active_day"], "2026-06-19")
        self.assertEqual(freshness["latest_covered_active_day"], "2026-06-19")
        self.assertEqual(freshness["live_forward_day_count"], 2)
        self.assertIn("Paper-score freshness", report)
        self.assertIn("PASS", report)

    def test_bounded_latest_n_selection_records_diagnostic_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root, old_run = write_minimal_run(root, "old-active", "mm_run_v0.2", "2026-06-18")
            _runs_root, mid_run = write_minimal_run(root, "mid-active", "mm_run_v0.2", "2026-06-19")
            _runs_root, new_run = write_minimal_run(root, "new-active", "mm_run_v0.2", "2026-06-20")
            mark_active_day(old_run)
            mark_active_day(mid_run)
            mark_active_day(new_run)

            payload = build_paper_payload(
                runs_root=runs_root,
                snapshots_root=root / "snapshots",
                backtest_root=root / "backtest",
                run_folder_latest_n=2,
            )
            payload, _known = write_outputs(
                payload,
                json_out=root / "backtest" / "mm_paper_report.json",
                report_out=root / "backtest" / "mm_paper_report.md",
                fills_out=root / "backtest" / "mm_paper_fills_long.csv",
                known_edge_out=root / "backtest" / "mm_known_edge_map.json",
                known_edge_report_out=root / "backtest" / "mm_known_edge_map.md",
            )
            report = (root / "backtest" / "mm_paper_report.md").read_text(encoding="utf-8")

        selection = payload["summary"]["run_folder_selection"]
        self.assertEqual(payload["summary"]["available_run_folders_before_selection"], 3)
        self.assertEqual(payload["summary"]["candidate_run_folders"], 2)
        self.assertTrue(payload["summary"]["bounded_run_selection"])
        self.assertEqual(selection["mode"], "bounded")
        self.assertEqual(selection["latest_n"], 2)
        self.assertEqual(selection["warning"], "diagnostic_selection_not_full_corpus")
        self.assertEqual(
            [Path(path).name for path in selection["selected_run_folders"]],
            ["mid-active", "new-active"],
        )
        self.assertIn("Run-folder selection", report)
        self.assertIn("diagnostic_selection_not_full_corpus", report)

    def test_target_date_and_evidence_mode_selection_filters_runs_before_scoring(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root, active_run = write_minimal_run(root, "active", "mm_run_v0.2", "2026-06-19")
            _runs_root, post_run = write_minimal_run(root, "post", "mm_run_v0.2", "2026-06-19")
            _runs_root, other_run = write_minimal_run(root, "other-date", "mm_run_v0.2", "2026-06-20")
            mark_active_day(active_run)
            mark_active_day(other_run)
            post_summary = json.loads((post_run / "run_summary.json").read_text(encoding="utf-8"))
            post_summary["evidence_mode"] = "post_settlement_evaluation"
            post_summary["generated_at_utc"] = "2026-06-20T02:00:00+00:00"
            (post_run / "run_summary.json").write_text(json.dumps(post_summary), encoding="utf-8")

            payload = build_paper_payload(
                runs_root=runs_root,
                snapshots_root=root / "snapshots",
                backtest_root=root / "backtest",
                run_folder_target_date="2026-06-19",
                run_folder_evidence_mode="active_day_live_forward",
            )

        selection = payload["summary"]["run_folder_selection"]
        self.assertEqual(payload["summary"]["available_run_folders_before_selection"], 3)
        self.assertEqual(payload["summary"]["candidate_run_folders"], 1)
        self.assertEqual(selection["mode"], "bounded")
        self.assertEqual(selection["target_date"], "2026-06-19")
        self.assertEqual(selection["evidence_mode"], "active_day_live_forward")
        self.assertEqual([Path(path).name for path in selection["selected_run_folders"]], ["active"])

    def test_bounded_run_uses_selected_target_date_for_exchange_economics_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root, run_folder = write_run_fixture(root)
            stale_snapshot = exchange_economics.build_snapshot_payload(
                target_date="2026-06-13",
                verified_at_utc="2026-06-14T17:00:00+00:00",
            )
            snapshot_path = write_json(root / "backtest" / "exchange_economics_snapshot.json", stale_snapshot)

            payload = build_paper_payload(
                runs_root=runs_root,
                snapshots_root=root / "snapshots",
                backtest_root=root / "backtest",
                run_folders=[run_folder],
                exchange_economics_snapshot_path=snapshot_path,
                exchange_economics_platform="polymarket_us",
                exchange_economics_required=True,
                include_fill_simulation=False,
                now="2026-06-14T17:00:00+00:00",
            )

        gate = payload["exchange_economics_gate"]
        self.assertEqual(gate["target_date"], TARGET_DATE)
        self.assertEqual(gate["verified_for_target_date"], "2026-06-13")
        self.assertEqual(gate["status"], "BLOCK")
        self.assertFalse(gate["checks"]["target_date_matches"])
        self.assertIn("target_date_matches", gate["missing"])

    def test_reward_score_diagnostics_use_polymarket_us_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root, run_folder = write_run_fixture(root)
            quote_rows = read_csv(run_folder / "quote_intents_long.csv")
            quote_rows[0]["book_spread"] = "0.02"
            write_csv(run_folder / "quote_intents_long.csv", list(quote_rows[0].keys()), quote_rows)
            snapshot = exchange_economics.build_snapshot_payload(
                target_date=TARGET_DATE,
                verified_at_utc="2026-06-14T17:00:00+00:00",
                tick_size=0.01,
                min_order_size=1.0,
                reward_formula="score = discount_factor ** ticks_from_best_price * order_size",
            )
            snapshot["liquidity_rewards"]["discount_factor_default"] = 0.3
            snapshot["liquidity_rewards"]["target_size_default_contracts"] = 100.0
            snapshot["liquidity_rewards"]["default_category_daily_reward_usd"] = 1000.0
            snapshot["liquidity_rewards"]["min_payout_usd"] = 1.0
            snapshot_path = write_json(root / "backtest" / "exchange_economics_snapshot.json", snapshot)

            payload = build_paper_payload(
                runs_root=runs_root,
                snapshots_root=root / "snapshots",
                backtest_root=root / "backtest",
                run_folders=[run_folder],
                exchange_economics_snapshot_path=snapshot_path,
                exchange_economics_target_date=TARGET_DATE,
                exchange_economics_platform="polymarket_us",
                exchange_economics_required=True,
                now="2026-06-14T17:00:00+00:00",
            )
            payload, _known = write_outputs(
                payload,
                json_out=root / "backtest" / "mm_paper_report.json",
                report_out=root / "backtest" / "mm_paper_report.md",
                fills_out=root / "backtest" / "mm_paper_fills_long.csv",
                known_edge_out=root / "backtest" / "mm_known_edge_map.json",
                known_edge_report_out=root / "backtest" / "mm_known_edge_map.md",
            )
            report = (root / "backtest" / "mm_paper_report.md").read_text(encoding="utf-8")

        diagnostics = payload["reward_score_diagnostics"]
        summary = payload["summary"]
        self.assertEqual(summary["quote_rows"], 1)
        self.assertEqual(summary["quote_permission_rows"], 1)
        self.assertEqual(summary["no_quote_rows"], 0)
        self.assertEqual(summary["quote_permission_rate"], 1.0)
        self.assertEqual(summary["quote_uptime"]["quote_permission_market_counts"], {"atlanta": 1})
        self.assertEqual(summary["quote_uptime"]["top_quote_permission_cells"][0]["market_id"], "atlanta")
        self.assertEqual(summary["quote_uptime"]["top_quote_permission_cells"][0]["range_label"], "80-81 F")
        self.assertEqual(summary["quote_uptime"]["top_quote_permission_cells"][0]["reason_code"], "QUOTE_HARVEST_MID")
        self.assertEqual(summary["quote_uptime"]["top_quote_permission_cells"][0]["rows"], 1)
        self.assertEqual(summary["live_trade_permission_rows"], 0)
        self.assertEqual(summary["live_trade_permission_rate"], 0.0)
        self.assertEqual(
            summary["gate_status_scope"],
            "paper_day_collection_and_exchange_economics_not_live_capital",
        )
        self.assertEqual(summary["live_capital_gate_status"], "NOT_EVALUATED_BY_MM_PAPER")
        self.assertIn("market_making_readiness", summary["live_capital_gate_reason"])
        self.assertEqual(diagnostics["status"], "PASS")
        self.assertEqual(diagnostics["score_basis"], "polymarket_us_discount_factor_ticks_from_best")
        self.assertEqual(diagnostics["positive_score_legs"], 2)
        self.assertEqual(diagnostics["total_reward_score"], 10.0)
        self.assertEqual(summary["total_reward_score"], diagnostics["total_reward_score"])
        self.assertEqual(diagnostics["score_to_target_size_fraction"], 0.1)
        self.assertFalse(diagnostics["score_at_or_above_target_size"])
        self.assertFalse(summary["score_at_or_above_target_size"])
        self.assertEqual(diagnostics["assumed_competitor_score"], 100.0)
        self.assertEqual(diagnostics["assumed_competitor_score_source"], "paper_config_reward_competitor_q")
        self.assertFalse(diagnostics["assumed_competitor_score_has_clob_recon_evidence"])
        self.assertAlmostEqual(diagnostics["counterfactual_score_share"], 0.09090909)
        self.assertAlmostEqual(summary["counterfactual_score_share"], 0.09090909)
        self.assertAlmostEqual(diagnostics["counterfactual_reward_usdc"], 90.909091)
        self.assertAlmostEqual(summary["counterfactual_reward_usdc"], 90.909091)
        self.assertEqual(diagnostics["counterfactual_reward_status"], "COUNTERFACTUAL_ONLY")
        self.assertEqual(summary["counterfactual_reward_status"], "COUNTERFACTUAL_ONLY")
        self.assertFalse(diagnostics["actual_payout_evidence"])
        self.assertFalse(summary["actual_payout_evidence"])
        self.assertTrue(diagnostics["does_not_change_pnl"])
        self.assertTrue(diagnostics["score_attribution_top_groups"])
        self.assertIn("## Reward Score Diagnostics", report)
        self.assertIn("Quote-intent rows / quoted legs", report)
        self.assertIn("| Quote-intent rows / quoted legs | 1 / 2 |", report)
        self.assertIn("Quote permissions / live permissions", report)
        self.assertIn("| Quote permissions / live permissions | 1 / 0 |", report)
        self.assertIn("Paper-day collection gate", report)
        self.assertIn("Live-capital gate", report)
        self.assertIn("NOT_EVALUATED_BY_MM_PAPER", report)
        self.assertNotIn("| Gate status |", report)
        self.assertIn("### Quote Permission Markets", report)
        self.assertIn("| Market | Quote-permission rows |", report)
        self.assertIn("| atlanta | 1 |", report)
        self.assertIn("### Top Quote Permission Cells", report)
        self.assertIn("| atlanta | 80-81 F |", report)
        self.assertIn("Counterfactual reward USDC", report)
        self.assertIn("Competitor score source", report)
        self.assertIn("polymarket_us_discount_factor_ticks_from_best", report)
        self.assertNotIn("Quote rows / legs", report)
        self.assertNotIn("| Market | Quote rows |", report)

    def test_reward_score_diagnostics_use_clob_recon_competitor_score_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root, run_folder = write_run_fixture(root)
            quote_rows = read_csv(run_folder / "quote_intents_long.csv")
            quote_rows[0]["book_spread"] = "0.02"
            write_csv(run_folder / "quote_intents_long.csv", list(quote_rows[0].keys()), quote_rows)
            snapshot = exchange_economics.build_snapshot_payload(
                target_date=TARGET_DATE,
                verified_at_utc="2026-06-14T17:00:00+00:00",
                tick_size=0.01,
                min_order_size=1.0,
                reward_formula="score = discount_factor ** ticks_from_best_price * order_size",
            )
            snapshot["liquidity_rewards"]["discount_factor_default"] = 0.3
            snapshot["liquidity_rewards"]["target_size_default_contracts"] = 100.0
            snapshot["liquidity_rewards"]["default_category_daily_reward_usd"] = 1000.0
            snapshot["liquidity_rewards"]["min_payout_usd"] = 1.0
            snapshot_path = write_json(root / "backtest" / "exchange_economics_snapshot.json", snapshot)
            recon = root / "backtest" / "clob_book_recon.json"
            write_json(recon, {
                "schema_version": "clob_book_recon_v0.1",
                "summary": {
                    "book_rows": 12,
                    "slice_rows": 3,
                    "policy_parameter_suggestions": {"reward_competitor_q": 10.0},
                },
                "policy_parameter_suggestions": {"reward_competitor_q": 10.0},
                "slices": [],
            })

            payload = build_paper_payload(
                runs_root=runs_root,
                snapshots_root=root / "snapshots",
                backtest_root=root / "backtest",
                run_folders=[run_folder],
                clob_recon_path=recon,
                exchange_economics_snapshot_path=snapshot_path,
                exchange_economics_target_date=TARGET_DATE,
                exchange_economics_platform="polymarket_us",
                exchange_economics_required=True,
                now="2026-06-14T17:00:00+00:00",
            )
            payload, _known = write_outputs(
                payload,
                json_out=root / "backtest" / "mm_paper_report.json",
                report_out=root / "backtest" / "mm_paper_report.md",
                fills_out=root / "backtest" / "mm_paper_fills_long.csv",
                known_edge_out=root / "backtest" / "mm_known_edge_map.json",
                known_edge_report_out=root / "backtest" / "mm_known_edge_map.md",
            )
            report = (root / "backtest" / "mm_paper_report.md").read_text(encoding="utf-8")

        diagnostics = payload["reward_score_diagnostics"]
        self.assertEqual(diagnostics["total_reward_score"], 10.0)
        self.assertEqual(diagnostics["assumed_competitor_score"], 10.0)
        self.assertEqual(
            diagnostics["assumed_competitor_score_source"],
            "clob_recon_policy_parameter_suggestions.reward_competitor_q",
        )
        self.assertTrue(diagnostics["assumed_competitor_score_has_clob_recon_evidence"])
        self.assertEqual(diagnostics["assumed_competitor_score_clob_recon_book_rows"], 12)
        self.assertEqual(diagnostics["assumed_competitor_score_clob_recon_slice_rows"], 3)
        self.assertAlmostEqual(diagnostics["counterfactual_score_share"], 0.5)
        self.assertAlmostEqual(diagnostics["counterfactual_reward_usdc"], 500.0)
        self.assertIn("clob_recon_policy_parameter_suggestions.reward_competitor_q", report)
        self.assertIn("12 books / 3 slices", report)

    def test_skip_model_variants_records_non_promotion_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root, run_folder = write_run_fixture(root)
            variant_row = read_csv(run_folder / "quote_intents_long.csv")[0]
            variant_row.update({
                "model_variant_id": "candidate_shadow",
                "model_variant_family": "dynamic_source_freshness",
                "model_variant_role": "shadow",
                "model_variant_counterfactual": "True",
            })
            write_csv(
                run_folder / "model_variant_quote_intents_long.csv",
                list(variant_row.keys()),
                [variant_row],
            )
            backtest_root = root / "backtest"
            promotion = backtest_root / "promotion.json"
            casebook = backtest_root / "casebook.json"
            write_promotion(promotion)
            write_casebook(casebook)

            payload = build_paper_payload(
                runs_root=runs_root,
                snapshots_root=root / "snapshots",
                backtest_root=backtest_root,
                run_folders=[run_folder],
                casebook_path=casebook,
                promotion_refresh=promotion,
                include_model_variants=False,
                now="2026-06-14T17:00:00+00:00",
            )
            payload, _known_edge = write_outputs(
                payload,
                json_out=backtest_root / "mm_paper_report.json",
                report_out=backtest_root / "mm_paper_report.md",
                fills_out=backtest_root / "mm_paper_fills_long.csv",
                known_edge_out=backtest_root / "mm_known_edge_map.json",
                known_edge_report_out=backtest_root / "mm_known_edge_map.md",
                promotion_refresh=promotion,
            )
            report = (backtest_root / "mm_paper_report.md").read_text(encoding="utf-8")

        self.assertEqual(payload["summary"]["quote_rows"], 1)
        self.assertEqual(payload["summary"]["quote_legs"], 2)
        self.assertFalse(payload["summary"]["model_variant_scoring_included"])
        self.assertEqual(payload["summary"]["model_variant_scoring_status"], "SKIPPED")
        self.assertEqual(payload["summary"]["model_variant_scoring_reason"], "skip_model_variants")
        self.assertEqual(payload["summary"]["model_variant_quote_rows"], 0)
        self.assertEqual(payload["summary"]["model_variant_quote_legs"], 0)
        self.assertEqual(payload["summary"]["model_variant_bakeoff"]["status"], "SKIPPED")
        self.assertEqual(payload["model_variant_bakeoff"]["promotion_gate"]["status"], "SKIPPED")
        self.assertEqual(payload["model_variant_fills"], [])
        self.assertEqual(payload["model_variant_queue_companion"], [])
        self.assertIn("Model-variant scoring", report)
        self.assertIn("skip_model_variants", report)

    def test_skip_fill_simulation_records_summary_only_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root, run_folder = write_run_fixture(root)
            variant_row = read_csv(run_folder / "quote_intents_long.csv")[0]
            variant_row.update({
                "model_variant_id": "candidate_shadow",
                "model_variant_family": "dynamic_source_freshness",
                "model_variant_role": "shadow",
                "model_variant_counterfactual": "True",
            })
            write_csv(
                run_folder / "model_variant_quote_intents_long.csv",
                list(variant_row.keys()),
                [variant_row],
            )
            backtest_root = root / "backtest"
            promotion = backtest_root / "promotion.json"
            casebook = backtest_root / "casebook.json"
            write_promotion(promotion)
            write_casebook(casebook)

            payload = build_paper_payload(
                runs_root=runs_root,
                snapshots_root=root / "missing_snapshots",
                backtest_root=backtest_root,
                run_folders=[run_folder],
                casebook_path=casebook,
                promotion_refresh=promotion,
                include_fill_simulation=False,
                now="2026-06-14T17:00:00+00:00",
            )
            payload, _known_edge = write_outputs(
                payload,
                json_out=backtest_root / "mm_paper_report.json",
                report_out=backtest_root / "mm_paper_report.md",
                fills_out=backtest_root / "mm_paper_fills_long.csv",
                known_edge_out=backtest_root / "mm_known_edge_map.json",
                known_edge_report_out=backtest_root / "mm_known_edge_map.md",
                promotion_refresh=promotion,
            )
            report = (backtest_root / "mm_paper_report.md").read_text(encoding="utf-8")

        self.assertEqual(payload["summary"]["quote_rows"], 1)
        self.assertEqual(payload["summary"]["quote_legs"], 2)
        self.assertFalse(payload["summary"]["fill_simulation_included"])
        self.assertEqual(payload["summary"]["fill_simulation_status"], "SKIPPED")
        self.assertEqual(payload["summary"]["fill_simulation_reason"], "skip_fill_simulation")
        self.assertEqual(payload["summary"]["conservative_fills"], 0)
        self.assertEqual(payload["summary"]["queue_estimated_fill_legs"], 0)
        self.assertEqual(payload["fill_evidence_completeness"]["status"], "SKIPPED")
        self.assertEqual(payload["summary"]["fill_evidence_completeness_status"], "SKIPPED")
        self.assertFalse(payload["fill_evidence_completeness"]["promotion_grade"])
        self.assertFalse(payload["summary"]["fill_evidence_promotion_grade"])
        self.assertIn("fill_simulation_skipped", payload["fill_evidence_completeness"]["blockers"])
        self.assertIn("fill_simulation_skipped", payload["summary"]["fill_evidence_blockers"])
        self.assertFalse(payload["summary"]["model_variant_scoring_included"])
        self.assertTrue(payload["summary"]["model_variant_scoring_requested"])
        self.assertEqual(payload["model_variant_bakeoff"]["reason"], "skip_fill_simulation")
        self.assertEqual(payload["model_variant_bakeoff"]["promotion_gate"]["status"], "SKIPPED")
        self.assertEqual(payload["fills"], [])
        self.assertEqual(payload["queue_companion"], [])
        self.assertIn("Fill simulation", report)
        self.assertIn("skip_fill_simulation", report)

    def test_paper_score_freshness_from_report_blocks_stale_standard_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root, old_run = write_minimal_run(root, "old-active", "mm_run_v0.2", "2026-06-18")
            mark_active_day(old_run)
            payload = build_paper_payload(
                runs_root=runs_root,
                snapshots_root=root / "snapshots",
                backtest_root=root / "backtest",
                run_folders=[old_run],
            )
            write_outputs(
                payload,
                json_out=root / "backtest" / "mm_paper_report.json",
                report_out=root / "backtest" / "mm_paper_report.md",
                fills_out=root / "backtest" / "mm_paper_fills_long.csv",
                known_edge_out=root / "backtest" / "mm_known_edge_map.json",
                known_edge_report_out=root / "backtest" / "mm_known_edge_map.md",
            )
            _runs_root, new_run = write_minimal_run(root, "new-active", "mm_run_v0.2", "2026-06-19")
            mark_active_day(new_run)

            freshness = maker_paper_score_freshness_from_report(
                runs_root,
                root / "backtest" / "mm_paper_report.json",
            )

        self.assertEqual(freshness["status"], "STALE")
        self.assertTrue(freshness["blocks_maker_evidence_countability"])
        self.assertEqual(freshness["latest_completed_active_day"], "2026-06-19")
        self.assertEqual(freshness["latest_covered_active_day"], "2026-06-18")

    def test_known_edge_map_prefers_promotion_allowlist_over_legacy_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            promotion = root / "promotion.json"
            promotion.write_text(json.dumps({
                "decisions": {
                    "markets": [
                        {
                            "market_id": "atlanta",
                            "action": "PROMOTE_CANDIDATE",
                            "verdict": "PASS",
                            "metrics": {"delta_vs_market": -0.01},
                        }
                    ]
                },
                "promotion_allowlist": {
                    "schema_version": "promotion_allowlist_v0.1",
                    "candidate_id": "candidate_v1",
                    "markets": [
                        {
                            "market_id": "atlanta",
                            "candidate_id": "candidate_v1",
                            "action": "BLOCK_CANDIDATE",
                            "verdict": "BLOCK",
                            "candidate_permission_allowed": False,
                            "candidate_serving_allowed": False,
                            "blocker_reason": "candidate trails market by +0.0148 > 0.0030",
                            "delta_vs_market": 0.0148,
                        }
                    ],
                },
            }), encoding="utf-8")
            paper_payload = {
                "schema_version": "mm_paper_v0.1",
                "summary": {
                    "conservative_fills": 8,
                    "anti_overfit": {"live_forward_days": ["2026-06-01"] * 14},
                },
                "markout_slices": [
                    {
                        "market_id": "atlanta",
                        "hour_utc": "15",
                        "band_distance_bucket": "edge_3c_8c",
                        "band_type": "eq",
                        "casebook_taxonomy": "market_lead",
                        "regime": "daytime",
                        "source_fresh": "true",
                        "book_imbalance_bucket": "balanced",
                        "fill_count": 8,
                        "markout_30m_ci_low": 0.02,
                        "net_pnl_after_fees_incentives_usdc": 3.0,
                    }
                ],
            }

            known_edge = build_known_edge_map(paper_payload, promotion_refresh=promotion)
            record = next(row for row in known_edge["records"] if row.get("cutoff") == "paper_slice")

        self.assertEqual(record["base_permission"], "BLOCK")
        self.assertEqual(record["permission"], "no_quote")
        self.assertEqual(record["reason"], "promotion_block")
        self.assertTrue(record["promotion"]["promotion_allowlist_enforced"])
        self.assertEqual(record["promotion"]["candidate_id"], "candidate_v1")

    def test_conservative_fills_queue_markouts_incentives_and_known_edge_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root, run_folder = write_run_fixture(root)
            base_quote = read_csv(run_folder / "quote_intents_long.csv")[0]
            served_variant = {
                **base_quote,
                "model_variant_id": "served_current",
                "model_variant_family": "served_current",
                "model_variant_role": "served",
                "model_variant_basket_id": "test_basket",
                "model_variant_probability_source": "served_fair_probability",
                "model_variant_counterfactual": "False",
                "served_model_version": "candidate",
                "edge": "0.0",
            }
            shadow_variant = {
                **base_quote,
                "model_variant_id": "external_dynamic",
                "model_variant_family": "dynamic_source_freshness",
                "model_variant_role": "shadow",
                "model_variant_basket_id": "test_basket",
                "model_variant_probability_source": "external_variant_row",
                "model_variant_counterfactual": "True",
                "served_model_version": "candidate",
                "fair_probability": "0.62",
                "edge": "0.12",
            }
            write_csv(
                run_folder / "model_variant_quote_intents_long.csv",
                list(served_variant.keys()),
                [served_variant, shadow_variant],
            )
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
            self.assertEqual(payload["summary"]["model_variant_bakeoff"]["status"], "PASS")
            self.assertGreaterEqual(payload["model_variant_bakeoff"]["conservative_fills"], 1)
            variant_rows = {
                row["model_variant_id"]: row
                for row in payload["model_variant_bakeoff"]["model_variant_by_policy"]
            }
            self.assertIn("served_current", variant_rows)
            self.assertIn("external_dynamic", variant_rows)
            self.assertEqual(
                payload["model_variant_bakeoff"]["promotion_gate"]["method"],
                "clustered_market_day_bootstrap",
            )
            self.assertEqual(payload["model_variant_bakeoff"]["promotion_gate"]["status"], "BLOCK")
            self.assertEqual(payload["summary"]["trade_evidence_gaps"]["missing_size_trade_rows"], 1)
            fill_gate = payload["fill_evidence_completeness"]
            self.assertEqual(fill_gate["status"], "BLOCK")
            self.assertIn("missing_size_trade_rows", fill_gate["blockers"])
            self.assertGreater(fill_gate["clob_recon_book_rows"], 0)
            self.assertGreater(fill_gate["clob_recon_slice_rows"], 0)
            self.assertTrue(fill_gate["by_market_hour_token"])
            self.assertIn("range_label", fill_gate["by_market_hour_token"][0])
            self.assertIn("side", fill_gate["by_market_hour_token"][0])
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
            report = Path(files["report"]).read_text(encoding="utf-8")
            self.assertIn("## Model-Variant Bakeoff", report)
            self.assertIn("Model-variant quote-intent rows / quoted legs", report)
            self.assertIn("| Variant | Policy | Quote-intent rows |", report)
            self.assertIn("## Fill Evidence Completeness", report)
            self.assertIn("### Top Event Data Gaps", report)
            self.assertIn("### Top Incomplete Market Data Slices", report)
            self.assertIn("YES_BID", report)
            self.assertIn("external_dynamic", report)
            self.assertNotIn("Model-variant quote rows / legs", report)
            self.assertNotIn("| Variant | Policy | Quote rows |", report)

            permissions = {(row["market_id"], row["permission"]) for row in known_edge["records"]}
            self.assertIn(("atlanta", "edge_research"), permissions)
            self.assertIn(("chicago", "harvest_only"), permissions)
            self.assertIn(("san-francisco", "no_quote"), permissions)

    def test_streamed_multi_run_scoring_matches_materialized_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root, first_run = write_run_fixture(root)
            first_quote = read_csv(first_run / "quote_intents_long.csv")[0]
            second_run = runs_root / TARGET_DATE / "paper-run-second"
            second_run.mkdir(parents=True)
            second_config = {
                "run_id": "paper-run-second",
                "mode": "paper-live-forward",
                "target_date": TARGET_DATE,
                "policy_hash": "locked-policy",
            }
            (second_run / "run_config.json").write_text(
                json.dumps(second_config),
                encoding="utf-8",
            )
            second_quote = {**first_quote, "run_id": "paper-run-second"}
            write_csv(
                second_run / "quote_intents_long.csv",
                list(second_quote.keys()),
                [second_quote],
            )
            for run_folder, base_quote in (
                (first_run, first_quote),
                (second_run, second_quote),
            ):
                served = {
                    **base_quote,
                    "model_variant_id": "served_current",
                    "model_variant_family": "served_current",
                    "model_variant_role": "served",
                    "model_variant_counterfactual": "False",
                }
                shadow = {
                    **base_quote,
                    "model_variant_id": "candidate_shadow",
                    "model_variant_family": "test",
                    "model_variant_role": "shadow",
                    "model_variant_counterfactual": "True",
                    "fair_probability": "0.62",
                }
                write_csv(
                    run_folder / "model_variant_quote_intents_long.csv",
                    list(served.keys()),
                    [served, shadow],
                )
            snapshots_root = write_snapshot_fixture(root)
            backtest_root = root / "backtest"
            casebook = backtest_root / "casebook.json"
            promotion = backtest_root / "promotion.json"
            write_casebook(casebook)
            write_promotion(promotion)
            kwargs = {
                "runs_root": runs_root,
                "snapshots_root": snapshots_root,
                "backtest_root": backtest_root,
                "run_folders": [first_run, second_run],
                "casebook_path": casebook,
                "promotion_refresh": promotion,
                "clob_recon_path": backtest_root / "clob_recon.json",
                "config": {"quote_ttl_seconds": 120.0},
                "now": "2026-06-14T17:00:00+00:00",
            }

            streamed = build_paper_payload(**kwargs, stream_run_inputs=True)
            materialized = build_paper_payload(**kwargs, stream_run_inputs=False)
            self.assertEqual(streamed, materialized)

            artifact_paths = {
                "json_out": backtest_root / "equivalence.json",
                "report_out": backtest_root / "equivalence.md",
                "fills_out": backtest_root / "equivalence_fills.csv",
                "known_edge_out": backtest_root / "equivalence_known_edge.json",
                "known_edge_report_out": backtest_root / "equivalence_known_edge.md",
                "promotion_refresh": promotion,
            }
            deferred = build_paper_payload(
                **kwargs,
                stream_run_inputs=True,
                materialize_output_rows=False,
            )
            write_outputs(deferred, **artifact_paths)
            deferred_artifact = json.loads(
                artifact_paths["json_out"].read_text(encoding="utf-8")
            )
            self.assertEqual(list(deferred["fills"]), streamed["fills"])
            self.assertEqual(
                list(deferred["queue_companion"]),
                streamed["queue_companion"],
            )
            deferred.close()
            write_outputs(materialized, **artifact_paths)
            materialized_artifact = json.loads(
                artifact_paths["json_out"].read_text(encoding="utf-8")
            )

        self.assertEqual(deferred_artifact, materialized_artifact)
        self.assertEqual(streamed["summary"]["quote_rows"], 2)
        self.assertEqual(streamed["summary"]["quote_legs"], 4)
        self.assertEqual(streamed["summary"]["conservative_fills"], 1)
        self.assertEqual(streamed["summary"]["conservative_filled_shares"], 3.0)
        self.assertEqual(len(streamed["queue_companion"]), 4)
        self.assertEqual(streamed["summary"]["model_variant_quote_rows"], 4)
        self.assertEqual(streamed["summary"]["model_variant_quote_legs"], 8)
        self.assertEqual(len(streamed["model_variant_fills"]), 1)

    def test_scoring_projection_is_byte_equivalent_to_canonical_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root, run_folder = write_run_fixture(root)
            legacy_quote = read_csv(run_folder / "quote_intents_long.csv")[0]
            quote = {
                column: legacy_quote.get(column, "")
                for column in RUN_QUOTE_COLUMNS
            }
            quote.update({
                "capture_hour_local": "4",
                "event_gate_next_event_at_utc": "2026-06-14T16:30:00+00:00",
                "book_spread": "0.02",
                "model_variant_runtime_identity": "fat-provenance-" + ("x" * 2048),
            })
            write_csv(
                run_folder / "quote_intents_long.csv",
                RUN_QUOTE_COLUMNS,
                [quote],
            )
            variants = [
                {
                    **quote,
                    "model_variant_id": "served_current",
                    "model_variant_family": "served_current",
                    "model_variant_role": "served",
                    "model_variant_counterfactual": "False",
                },
                {
                    **quote,
                    "model_variant_id": "candidate_shadow",
                    "model_variant_family": "test",
                    "model_variant_role": "shadow",
                    "model_variant_counterfactual": "True",
                    "fair_probability": "0.62",
                },
            ]
            write_csv(
                run_folder / "model_variant_quote_intents_long.csv",
                RUN_QUOTE_COLUMNS,
                variants,
            )
            config = json.loads((run_folder / "run_config.json").read_text(encoding="utf-8"))
            config["schema_version"] = "mm_run_v0.2"
            (run_folder / "run_config.json").write_text(
                json.dumps(config),
                encoding="utf-8",
            )
            receipt = write_run_scoring_projections(run_folder)
            resolved = resolve_run_scoring_inputs(run_folder)
            self.assertEqual(resolved["input_mode"], "projection")

            snapshots_root = write_snapshot_fixture(root)
            backtest_root = root / "backtest"
            casebook = backtest_root / "casebook.json"
            promotion = backtest_root / "promotion.json"
            write_casebook(casebook)
            write_promotion(promotion)
            kwargs = {
                "runs_root": runs_root,
                "snapshots_root": snapshots_root,
                "backtest_root": backtest_root,
                "run_folders": [run_folder],
                "casebook_path": casebook,
                "promotion_refresh": promotion,
                "clob_recon_path": backtest_root / "clob_recon.json",
                "config": {"quote_ttl_seconds": 120.0},
                "now": "2026-06-14T17:00:00+00:00",
            }
            canonical = build_paper_payload(**kwargs)
            projected = build_paper_payload(
                **kwargs,
                scoring_input_paths_by_folder={
                    str(run_folder): receipt["input_paths"],
                },
                scoring_input_bindings_by_folder={
                    str(run_folder): receipt["input_bindings"],
                },
            )
            canonical_path = backtest_root / "canonical_score.json"
            projected_path = backtest_root / "projected_score.json"
            write_scoring_json(canonical_path, canonical)
            write_scoring_json(projected_path, projected)
            self.assertEqual(canonical_path.read_bytes(), projected_path.read_bytes())

            projection_path = Path(receipt["input_paths"]["base"])
            projection_path.write_bytes(projection_path.read_bytes() + b"\n")
            with self.assertRaisesRegex(RuntimeError, "binding mismatch"):
                build_paper_payload(
                    **kwargs,
                    scoring_input_paths_by_folder={
                        str(run_folder): receipt["input_paths"],
                    },
                    scoring_input_bindings_by_folder={
                        str(run_folder): receipt["input_bindings"],
                    },
                )

    def test_streamed_build_peak_memory_stays_roughly_flat_as_runs_grow(self):
        def measured_peak(run_count):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                run_folders = [
                    write_no_quote_run_fixture(root, run_index, row_count=256)
                    for run_index in range(run_count)
                ]
                gc.collect()
                tracemalloc.start()
                try:
                    payload = build_paper_payload(
                        runs_root=root / "mm_runs",
                        snapshots_root=root / "snapshots",
                        backtest_root=root / "backtest",
                        run_folders=run_folders,
                        casebook_path=root / "backtest" / "casebook.json",
                        clob_recon_path=root / "backtest" / "clob_recon.json",
                        known_edge_coverage_map=root / "backtest" / "known_edge.json",
                        exchange_economics_snapshot_path=(
                            root / "backtest" / "exchange_economics.json"
                        ),
                        exchange_economics_required=False,
                        now="2026-06-30T17:00:00+00:00",
                        stream_run_inputs=True,
                        materialize_output_rows=False,
                    )
                    json_out = root / "backtest" / "mm_paper.json"
                    write_outputs(
                        payload,
                        json_out=json_out,
                        report_out=root / "backtest" / "mm_paper.md",
                        fills_out=root / "backtest" / "mm_paper_fills.csv",
                        known_edge_out=root / "backtest" / "known_edge.json",
                        known_edge_report_out=root / "backtest" / "known_edge.md",
                        promotion_refresh=root / "backtest" / "promotion.json",
                    )
                    counts = {
                        "runs": payload["summary"]["run_folders"],
                        "quote_rows": payload["summary"]["quote_rows"],
                        "quote_legs": payload["summary"]["quote_legs"],
                        "model_variant_quote_rows": payload["summary"][
                            "model_variant_quote_rows"
                        ],
                        "model_variant_quote_legs": payload["summary"][
                            "model_variant_quote_legs"
                        ],
                    }
                    payload.close()
                    _current, peak = tracemalloc.get_traced_memory()
                finally:
                    tracemalloc.stop()
                artifact = json.loads(json_out.read_text(encoding="utf-8"))
                counts["queue_rows"] = len(artifact["queue_companion"])
                counts["model_variant_queue_rows"] = len(
                    artifact["model_variant_queue_companion"]
                )
            return peak, counts

        small_peak, small_counts = measured_peak(5)
        large_peak, large_counts = measured_peak(50)

        self.assertEqual(
            small_counts,
            {
                "runs": 5,
                "quote_rows": 5 * 256,
                "quote_legs": 5 * 32 * 2,
                "model_variant_quote_rows": 5 * 256,
                "model_variant_quote_legs": 5 * 32 * 2,
                "queue_rows": 5 * 32 * 2,
                "model_variant_queue_rows": 5 * 32 * 2,
            },
        )
        self.assertEqual(
            large_counts,
            {
                "runs": 50,
                "quote_rows": 50 * 256,
                "quote_legs": 50 * 32 * 2,
                "model_variant_quote_rows": 50 * 256,
                "model_variant_quote_legs": 50 * 32 * 2,
                "queue_rows": 50 * 32 * 2,
                "model_variant_queue_rows": 50 * 32 * 2,
            },
        )
        self.assertLessEqual(large_peak, small_peak + 2 * 1024 * 1024)

    def test_streaming_json_preserves_existing_artifact_on_error(self):
        class BrokenRows:
            is_spilled_rows = True

            def __iter__(self):
                yield {"row": 1}
                raise RuntimeError("synthetic serialization failure")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "paper.json"
            output.write_text("existing-artifact\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "synthetic serialization failure"):
                write_scoring_json(output, {"rows": BrokenRows()})

            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "existing-artifact\n",
            )
            self.assertEqual(list(root.glob(f".{output.name}.*.tmp")), [])

    def test_early_hour_guardrail_shadow_compares_loss_reduction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root = root / "mm_runs"
            run_folder = runs_root / TARGET_DATE / "early-hour-run"
            run_folder.mkdir(parents=True)
            (run_folder / "run_config.json").write_text(json.dumps({
                "run_id": "early-hour-run",
                "mode": "paper-live-forward",
                "target_date": TARGET_DATE,
                "policy_hash": "locked-policy",
            }), encoding="utf-8")
            quote_row = {
                "run_id": "early-hour-run",
                "target_date": TARGET_DATE,
                "run_mode": "paper-live-forward",
                "generated_at_utc": "2026-06-14T09:00:00+00:00",
                "captured_at_utc": "2026-06-14T08:59:30+00:00",
                "policy_hash": "locked-policy",
                "quote_permission": "True",
                "market_id": "atlanta",
                "event_slug": EVENT,
                "range_label": "80-81 F",
                "bin_kind": "eq",
                "bin_value": "80",
                "bin_value_hi": "81",
                "clob_token_id": "token-early",
                "fair_probability": "0.52",
                "market_mid": "0.50",
                "bid_price": "0.49",
                "bid_size": "5",
                "ask_price": "",
                "ask_size": "",
                "regime": "harvest",
                "source_fresh": "True",
                "source_freshness_state": "failed:open_meteo",
                "book_imbalance_1pct": "0.10",
                "min_order_size": "1",
                "reason_code": "QUOTE_HARVEST_MID",
            }
            write_csv(run_folder / "quote_intents_long.csv", list(quote_row.keys()), [quote_row])

            snapshots_root = root / "snapshots"
            folder = snapshots_root / EVENT
            folder.mkdir(parents=True)
            trades = [
                {
                    "trade_time_utc": "2026-06-14T09:00:10+00:00",
                    "clob_token_id": "token-early",
                    "price": "0.48",
                    "size": "5",
                    "side": "SELL",
                },
            ]
            write_csv(folder / "trades_long.csv", list(trades[0].keys()), trades)
            books = [
                {
                    "captured_at_utc": "2026-06-14T08:59:50+00:00",
                    "event_slug": EVENT,
                    "market_id": "atlanta",
                    "range_label": "80-81 F",
                    "bin_kind": "eq",
                    "bin_value": "80",
                    "bin_value_hi": "81",
                    "clob_token_id": "token-early",
                    "best_bid": "0.49",
                    "best_ask": "0.51",
                    "midpoint": "0.50",
                    "bid_size_at_best": "10",
                    "ask_size_at_best": "10",
                    "bid_depth_1pct": "10",
                    "ask_depth_1pct": "10",
                    "tick_size": "0.001",
                },
            ]
            write_csv(folder / "order_books_summary.csv", list(books[0].keys()), books)
            marks = [
                {
                    "point_time_utc": "2026-06-14T09:30:30+00:00",
                    "clob_token_id": "token-early",
                    "price": "0.40",
                },
            ]
            write_csv(folder / "price_history.csv", list(marks[0].keys()), marks)
            (folder / "settlement.json").write_text(json.dumps({
                "event_slug": EVENT,
                "market_id": "atlanta",
                "settlement_bucket": 79,
                "winning_band": "79-80 F",
                "quality_grade": "complete",
            }), encoding="utf-8")

            payload = build_paper_payload(
                runs_root=runs_root,
                snapshots_root=snapshots_root,
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

            shadow = payload["summary"]["early_hour_guardrail_shadow"]
            self.assertEqual(shadow["status"], "REDUCED_EARLY_HOUR_LOSS")
            self.assertEqual(shadow["early_hour_fill_rows"], 1)
            self.assertGreater(shadow["early_hour_market_aware_delta_vs_base_usdc"], 0.0)
            self.assertGreater(shadow["early_hour_base_loss_usdc"], shadow["early_hour_capped_loss_usdc"])
            self.assertEqual(shadow["early_hour_market_aware_loss_usdc"], 0.0)
            exposure = shadow["quote_exposure"]
            self.assertEqual(exposure["early_hour_quote_rows"], 1)
            self.assertEqual(exposure["market_aware_standdown_rows"], 1)
            fill = payload["fills"][0]
            self.assertEqual(fill["hourly_trust_band"], "early_00_08")
            self.assertEqual(fill["early_hour_guardrail_status"], "active")
            self.assertAlmostEqual(float(fill["fair_probability"]), 0.52)
            report = (root / "backtest" / "mm_paper_report.md").read_text(encoding="utf-8")
            self.assertIn("## Early-Hour Market-Aware Guardrail", report)
            self.assertIn("Early-hour quote-permission rows", report)
            self.assertNotIn("Early-hour quote rows", report)

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
                "known_edge_allowed": "False",
                "known_edge_permission": "harvest_only",
                "known_edge_reason": "awaiting_paper_markouts",
                "promotion_state": "SHADOW",
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
            blockers = payload["summary"]["quote_blocker_diagnostics"]
            self.assertEqual(blockers["blocked_rows"], 1)
            self.assertEqual(blockers["event_gate_suppressed_rows"], 1)
            self.assertEqual(blockers["contextual_event_gate_suppressed_rows"], 1)
            self.assertEqual(blockers["known_edge_permission_blocked_rows"], 0)
            self.assertEqual(blockers["known_edge_blocked_rows"], 0)
            self.assertEqual(blockers["known_edge_allowed_false_rows"], 1)
            self.assertEqual(blockers["known_edge_state_rows"], 1)
            self.assertEqual(blockers["harvest_only_suppressed_by_other_gate_rows"], 1)
            self.assertEqual(blockers["reason_counts"]["NO_QUOTE_INFORMATION_EVENT"], 1)
            self.assertEqual(blockers["top_market_reasons"][0]["market_id"], "atlanta")
            self.assertEqual(blockers["top_event_gate_states"][0]["event_gate_reason_code"], "INFO_EVENT_METAR_PRINT")
            overlap = blockers["top_blocker_overlaps"][0]
            self.assertEqual(overlap["reason_code"], "NO_QUOTE_INFORMATION_EVENT")
            self.assertEqual(overlap["event_gate_action"], "suppress")
            self.assertEqual(overlap["event_gate_reason_code"], "INFO_EVENT_METAR_PRINT")
            self.assertEqual(overlap["known_edge_permission"], "harvest_only")
            self.assertEqual(overlap["known_edge_reason"], "awaiting_paper_markouts")
            self.assertEqual(overlap["promotion_state"], "SHADOW")
            report = (root / "backtest" / "mm_paper_report.md").read_text(encoding="utf-8")
            self.assertIn("## Information Event Gate", report)
            self.assertIn("## Quote Blocker Diagnostics", report)
            self.assertIn("| Quote-intent rows | 1 |", report)
            self.assertIn("### Top Blocker Overlaps", report)
            self.assertIn("NO_QUOTE_INFORMATION_EVENT", report)
            self.assertNotIn("| Quote rows | 1 |", report)

    def test_quote_blocker_diagnostics_distinguishes_contextual_event_suppress(self):
        blockers = quote_blocker_diagnostics(
            [
                {
                    "_quote_id": "preflight-source",
                    "market_id": "atlanta",
                    "range_label": "80-81 F",
                    "reason_code": "NO_QUOTE_MISSING_PREFLIGHT",
                    "event_gate_action": "suppress",
                    "event_gate_status": "PULL",
                    "event_gate_reason_code": "INFO_EVENT_METAR_PRINT",
                    "known_edge_permission": "harvest_only",
                    "known_edge_reason": "missing_known_edge_record",
                    "promotion_state": "SHADOW",
                }
            ],
            legs=[],
            known_edge_records=[],
            known_edge_map_diag={},
        )

        self.assertEqual(blockers["blocked_rows"], 1)
        self.assertEqual(blockers["reason_counts"]["NO_QUOTE_MISSING_PREFLIGHT"], 1)
        self.assertEqual(blockers["event_gate_suppressed_rows"], 0)
        self.assertEqual(blockers["contextual_event_gate_suppressed_rows"], 1)
        self.assertEqual(blockers["harvest_only_suppressed_by_other_gate_rows"], 0)
        self.assertEqual(blockers["top_event_gate_states"][0]["event_gate_action"], "suppress")

    def test_no_quote_legs_are_not_promotion_grade_fill_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root = root / "mm_runs"
            run_folder = runs_root / TARGET_DATE / "no-quote-run"
            run_folder.mkdir(parents=True)
            run_config = {
                "schema_version": "mm_run_v0.2",
                "run_id": "no-quote-run",
                "mode": "paper-live-forward",
                "target_date": TARGET_DATE,
                "policy_hash": "locked-policy",
            }
            (run_folder / "run_config.json").write_text(json.dumps(run_config), encoding="utf-8")
            (run_folder / "run_summary.json").write_text(json.dumps({
                **run_config,
                "preflight_status": "PASS",
            }), encoding="utf-8")
            quote_row = {
                "run_id": "no-quote-run",
                "target_date": TARGET_DATE,
                "run_mode": "paper-live-forward",
                "generated_at_utc": "2026-06-14T14:05:00+00:00",
                "captured_at_utc": "2026-06-14T14:04:30+00:00",
                "policy_hash": "locked-policy",
                "quote_permission": "False",
                "live_trade_permission": "False",
                "reason_code": "NO_QUOTE_KNOWN_EDGE_PERMISSION",
                "market_id": "dallas",
                "event_slug": EVENT,
                "range_label": "92-93 F",
                "bin_kind": "eq",
                "regime": "none",
                "source_fresh": "True",
                "known_edge_allowed": "False",
                "known_edge_permission": "no_quote",
                "known_edge_reason": "missing_known_edge_record",
                "promotion_state": "SHADOW",
                "fair_probability": "0.540",
                "market_mid": "0.535",
            }
            write_csv(run_folder / "quote_intents_long.csv", list(quote_row.keys()), [quote_row])

            payload = build_paper_payload(
                runs_root=runs_root,
                snapshots_root=root / "snapshots",
                backtest_root=root / "backtest",
                run_folders=[run_folder],
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

            fill_gate = payload["fill_evidence_completeness"]
            self.assertEqual(payload["summary"]["quote_rows"], 1)
            self.assertEqual(payload["summary"]["quote_permission_rows"], 0)
            self.assertEqual(payload["summary"]["quote_legs"], 0)
            self.assertEqual(fill_gate["status"], "BLOCK")
            self.assertFalse(fill_gate["promotion_grade"])
            self.assertTrue(fill_gate["vacuous"])
            self.assertEqual(fill_gate["reason"], "no_quote_legs")
            self.assertIn("no_quote_legs", fill_gate["blockers"])
            self.assertEqual(payload["summary"]["fill_evidence_completeness_status"], "BLOCK")
            self.assertFalse(payload["summary"]["fill_evidence_promotion_grade"])
            self.assertTrue(payload["summary"]["fill_evidence_vacuous"])
            self.assertEqual(payload["summary"]["fill_evidence_reason"], "no_quote_legs")
            self.assertEqual(
                payload["summary"]["gate_status_scope"],
                "paper_day_collection_and_exchange_economics_not_live_capital",
            )
            self.assertEqual(payload["summary"]["live_capital_gate_status"], "NOT_EVALUATED_BY_MM_PAPER")
            report = (root / "backtest" / "mm_paper_report.md").read_text(encoding="utf-8")
            self.assertIn("Paper-day collection gate", report)
            self.assertIn("Live-capital gate", report)
            self.assertNotIn("| Gate status |", report)
            self.assertIn("no_quote_legs", report)
            self.assertIn("| Vacuous | True |", report)

    def test_quote_blocker_diagnostics_exposes_missing_known_edge_dimensions(self):
        quote_rows = [
            {
                "_quote_id": "row-missing-edge",
                "generated_at_utc": "2026-06-14T14:05:00+00:00",
                "captured_at_utc": "2026-06-14T14:04:30+00:00",
                "market_id": "dallas",
                "range_label": "92-93 F",
                "reason_code": "NO_QUOTE_KNOWN_EDGE_PERMISSION",
                "known_edge_allowed": "False",
                "known_edge_permission": "no_quote",
                "known_edge_reason": "missing_known_edge_record",
                "promotion_state": "SHADOW",
                "bin_kind": "eq",
                "regime": "none",
                "source_fresh": "True",
                "source_freshness_state": "all_fresh",
                "fair_probability": "0.540",
                "market_mid": "0.535",
                "book_imbalance_1pct": "0.30",
            }
        ]

        known_edge_records = [
            {
                "market_id": "dallas",
                "hour_utc": "14",
                "band_distance_bucket": "edge_lt_1c",
                "band_type": "eq",
                "casebook_taxonomy": "*",
                "regime": "none",
                "source_freshness_state": "all_fresh",
                "book_imbalance_bucket": "bid_heavy",
                "permission": "harvest_only",
                "reason": "diagnostic_candidate",
            }
        ]

        blockers = quote_blocker_diagnostics(
            quote_rows,
            legs=[],
            known_edge_records=known_edge_records,
            known_edge_map_diag={
                "path": "known-edge-map.json",
                "exists": True,
                "schema_version": "mm_known_edge_map_v0.2",
                "record_count": 1,
            },
        )

        self.assertEqual(blockers["schema_version"], "mm_quote_blocker_diagnostics_v0.8")
        self.assertEqual(blockers["known_edge_permission_blocked_rows"], 1)
        self.assertEqual(blockers["quote_permission_rows"], 0)
        self.assertEqual(blockers["inferred_known_edge_record_match_rows"], 1)
        self.assertEqual(blockers["inferred_known_edge_record_miss_rows"], 0)
        self.assertEqual(blockers["known_edge_coverage_map"]["record_count"], 1)
        missing = blockers["top_missing_known_edge_dimensions"][0]
        self.assertEqual(missing["market_id"], "dallas")
        self.assertEqual(missing["hour_utc"], "14")
        self.assertEqual(missing["band_distance_bucket"], "(missing)")
        self.assertEqual(missing["band_type"], "eq")
        self.assertEqual(missing["casebook_taxonomy"], "(missing)")
        self.assertEqual(missing["regime"], "none")
        self.assertEqual(missing["source_freshness_state"], "all_fresh")
        self.assertEqual(missing["book_imbalance_bucket"], "(missing)")
        self.assertEqual(missing["promotion_state"], "SHADOW")
        self.assertEqual(missing["rows"], 1)
        inferred = blockers["top_inferred_missing_known_edge_dimensions"][0]
        self.assertEqual(inferred["market_id"], "dallas")
        self.assertEqual(inferred["hour_utc"], "14")
        self.assertEqual(inferred["band_distance_bucket"], "edge_lt_1c")
        self.assertEqual(inferred["band_type"], "eq")
        self.assertEqual(inferred["casebook_taxonomy"], "(missing)")
        self.assertEqual(inferred["regime"], "none")
        self.assertEqual(inferred["source_freshness_state"], "all_fresh")
        self.assertEqual(inferred["book_imbalance_bucket"], "bid_heavy")
        self.assertEqual(inferred["promotion_state"], "SHADOW")
        self.assertEqual(inferred["rows"], 1)
        match = blockers["top_inferred_known_edge_record_matches"][0]
        self.assertEqual(match["market_id"], "dallas")
        self.assertEqual(match["record_permission"], "harvest_only")
        self.assertEqual(match["record_reason"], "diagnostic_candidate")
        self.assertIn("dallas|*", match["record_key"])
        action = blockers["top_known_edge_coverage_action_items"][0]
        self.assertEqual(action["market_id"], "dallas")
        self.assertEqual(action["required_action"], "populate_policy_match_dimensions_then_retest")
        self.assertEqual(action["nearest_record_permission"], "harvest_only")
        self.assertEqual(action["nearest_record_reason"], "diagnostic_candidate")
        self.assertEqual(action["mismatched_dimensions"], "")
        required_action = blockers["top_known_edge_required_actions"][0]
        self.assertEqual(
            required_action["required_action"],
            "populate_policy_match_dimensions_then_retest",
        )
        self.assertEqual(required_action["known_edge_reason"], "missing_known_edge_record")
        self.assertEqual(required_action["known_edge_permission"], "no_quote")
        self.assertEqual(required_action["promotion_state"], "SHADOW")
        self.assertEqual(required_action["rows"], 1)

    def test_quote_blocker_diagnostics_exposes_nearest_known_edge_gap(self):
        quote_rows = [
            {
                "_quote_id": "row-missing-edge",
                "generated_at_utc": "2026-06-14T15:05:00+00:00",
                "captured_at_utc": "2026-06-14T15:04:30+00:00",
                "market_id": "dallas",
                "range_label": "92-93 F",
                "reason_code": "NO_QUOTE_KNOWN_EDGE_PERMISSION",
                "known_edge_allowed": "False",
                "known_edge_permission": "no_quote",
                "known_edge_reason": "missing_known_edge_record",
                "promotion_state": "SHADOW",
                "bin_kind": "eq",
                "regime": "none",
                "source_fresh": "True",
                "source_freshness_state": "all_fresh",
                "fair_probability": "0.540",
                "market_mid": "0.535",
                "book_imbalance_1pct": "0.30",
            }
        ]
        known_edge_records = [
            {
                "market_id": "dallas",
                "hour_utc": "14",
                "band_distance_bucket": "edge_lt_1c",
                "band_type": "eq",
                "casebook_taxonomy": "*",
                "regime": "harvest",
                "source_freshness_state": "all_fresh",
                "book_imbalance_bucket": "bid_heavy",
                "permission": "harvest_only",
                "reason": "diagnostic_candidate",
            }
        ]

        blockers = quote_blocker_diagnostics(
            quote_rows,
            legs=[],
            known_edge_records=known_edge_records,
            known_edge_map_diag={"exists": True, "record_count": 1},
        )

        self.assertEqual(blockers["schema_version"], "mm_quote_blocker_diagnostics_v0.8")
        self.assertEqual(blockers["inferred_known_edge_record_match_rows"], 0)
        self.assertEqual(blockers["inferred_known_edge_record_miss_rows"], 1)
        gap = blockers["top_inferred_known_edge_nearest_record_gaps"][0]
        self.assertEqual(gap["market_id"], "dallas")
        self.assertEqual(gap["hour_utc"], "15")
        self.assertEqual(gap["nearest_record_permission"], "harvest_only")
        self.assertEqual(gap["nearest_record_reason"], "diagnostic_candidate")
        self.assertEqual(gap["matched_dimension_count"], "4")
        self.assertEqual(gap["mismatched_dimension_count"], "2")
        self.assertEqual(gap["mismatched_dimensions"], "hour_utc:15!=14; regime:none!=harvest")
        self.assertIn("dallas|*", gap["nearest_record_key"])
        action = blockers["top_known_edge_coverage_action_items"][0]
        self.assertEqual(action["market_id"], "dallas")
        self.assertEqual(action["required_action"], "collect_countable_markouts_before_map_change")
        self.assertEqual(action["nearest_record_permission"], "harvest_only")
        self.assertEqual(action["mismatched_dimensions"], "hour_utc:15!=14; regime:none!=harvest")
        required_action = blockers["top_known_edge_required_actions"][0]
        self.assertEqual(
            required_action["required_action"],
            "collect_countable_markouts_before_map_change",
        )
        self.assertEqual(required_action["known_edge_reason"], "missing_known_edge_record")
        self.assertEqual(required_action["known_edge_permission"], "no_quote")
        self.assertEqual(required_action["promotion_state"], "SHADOW")
        self.assertEqual(required_action["rows"], 1)

    def test_report_renders_missing_known_edge_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root = root / "mm_runs"
            run_folder = runs_root / TARGET_DATE / "missing-known-edge-run"
            run_folder.mkdir(parents=True)
            run_config = {
                "schema_version": "mm_run_v0.2",
                "run_id": "missing-known-edge-run",
                "mode": "paper-live-forward",
                "target_date": TARGET_DATE,
                "policy_hash": "locked-policy",
            }
            (run_folder / "run_config.json").write_text(json.dumps(run_config), encoding="utf-8")
            (run_folder / "run_summary.json").write_text(json.dumps({
                **run_config,
                "preflight_status": "PASS",
            }), encoding="utf-8")
            quote_row = {
                "run_id": "missing-known-edge-run",
                "target_date": TARGET_DATE,
                "run_mode": "paper-live-forward",
                "generated_at_utc": "2026-06-14T14:05:00+00:00",
                "captured_at_utc": "2026-06-14T14:04:30+00:00",
                "policy_hash": "locked-policy",
                "quote_permission": "False",
                "reason_code": "NO_QUOTE_KNOWN_EDGE_PERMISSION",
                "market_id": "dallas",
                "event_slug": EVENT,
                "range_label": "92-93 F",
                "bin_kind": "eq",
                "regime": "none",
                "source_fresh": "True",
                "source_freshness_state": "all_fresh",
                "known_edge_allowed": "False",
                "known_edge_permission": "no_quote",
                "known_edge_reason": "missing_known_edge_record",
                "promotion_state": "SHADOW",
                "fair_probability": "0.540",
                "market_mid": "0.535",
                "book_imbalance_1pct": "0.30",
            }
            quote_row_miss = {
                **quote_row,
                "generated_at_utc": "2026-06-14T15:05:00+00:00",
                "captured_at_utc": "2026-06-14T15:04:30+00:00",
                "range_label": "94-95 F",
                "reason_code": "NO_QUOTE_STALE_INPUT",
            }
            write_csv(run_folder / "quote_intents_long.csv", list(quote_row.keys()), [quote_row, quote_row_miss])
            backtest_root = root / "backtest"
            backtest_root.mkdir(parents=True)
            (backtest_root / "mm_known_edge_map.json").write_text(json.dumps({
                "schema_version": "mm_known_edge_map_v0.2",
                "records": [
                    {
                        "market_id": "dallas",
                        "hour_utc": "14",
                        "band_distance_bucket": "edge_lt_1c",
                        "band_type": "eq",
                        "casebook_taxonomy": "*",
                        "regime": "none",
                        "source_freshness_state": "all_fresh",
                        "book_imbalance_bucket": "bid_heavy",
                        "permission": "harvest_only",
                        "reason": "diagnostic_candidate",
                    }
                ],
            }), encoding="utf-8")

            payload = build_paper_payload(
                runs_root=runs_root,
                snapshots_root=root / "snapshots",
                backtest_root=backtest_root,
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

            blockers = payload["summary"]["quote_blocker_diagnostics"]
            self.assertEqual(blockers["schema_version"], "mm_quote_blocker_diagnostics_v0.8")
            self.assertEqual(blockers["top_missing_known_edge_dimensions"][0]["market_id"], "dallas")
            self.assertEqual(blockers["inferred_known_edge_record_match_rows"], 1)
            self.assertEqual(blockers["inferred_known_edge_record_miss_rows"], 1)
            self.assertEqual(blockers["quote_permission_rows"], 0)
            self.assertEqual(blockers["known_edge_permission_blocked_rows"], 1)
            self.assertEqual(blockers["stale_input_blocked_rows"], 1)
            self.assertEqual(blockers["stale_input_rows"], 1)
            report = (root / "backtest" / "mm_paper_report.md").read_text(encoding="utf-8")
            self.assertIn("| Stale-input blocked rows | 1 |", report)
            self.assertIn("### Top Missing Known-Edge Dimensions", report)
            expected_row = (
                "| dallas | 14 | (missing) | eq | (missing) | none | "
                "all_fresh | (missing) | SHADOW | 1 |"
            )
            self.assertIn(expected_row, report)
            self.assertIn("### Top Inferred Missing Known-Edge Dimensions", report)
            expected_inferred_row = (
                "| dallas | 14 | edge_lt_1c | eq | (missing) | none | "
                "all_fresh | bid_heavy | SHADOW | 1 |"
            )
            self.assertIn(expected_inferred_row, report)
            self.assertIn("### Known-Edge Coverage Map", report)
            self.assertIn("### Inferred Known-Edge Record Matches", report)
            self.assertIn("| dallas | 14 | edge_lt_1c | eq | (missing) | none | all_fresh | bid_heavy | SHADOW | harvest_only | diagnostic_candidate | 1 |", report)
            self.assertIn("### Inferred Known-Edge Nearest Record Gaps", report)
            expected_gap_row = (
                "| dallas | 15 | edge_lt_1c | eq | (missing) | none | all_fresh | bid_heavy | "
                "SHADOW | harvest_only | diagnostic_candidate | 5 | 1 | hour_utc:15!=14 | 1 |"
            )
            self.assertIn(expected_gap_row, report)
            self.assertIn("### Known-Edge Coverage Action Items", report)
            self.assertIn("### Known-Edge Required Actions", report)
            self.assertIn(
                "| populate_policy_match_dimensions_then_retest | missing_known_edge_record | no_quote | SHADOW | 1 |",
                report,
            )
            self.assertIn("These rows are diagnostic only.", report)
            self.assertIn(
                "| dallas | 14 | edge_lt_1c | eq | (missing) | none | all_fresh | bid_heavy | "
                "missing_known_edge_record | no_quote | SHADOW | "
                "populate_policy_match_dimensions_then_retest | harvest_only | - | 1 |",
                report,
            )
            self.assertIn("### Top Blocker Overlaps", report)
            self.assertIn(
                "| NO_QUOTE_KNOWN_EDGE_PERMISSION | unknown | unknown | no_quote | "
                "missing_known_edge_record | SHADOW | 1 |",
                report,
            )
            self.assertIn(
                "| NO_QUOTE_STALE_INPUT | unknown | unknown | no_quote | "
                "missing_known_edge_record | SHADOW | 1 |",
                report,
            )

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

    def test_per_market_live_forward_credit_survives_one_stale_market_but_broad_gate_stays_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root, old_run = write_minimal_run(root, "old-v1", "mm_run_v0.1", "2026-06-16")
            _runs_root, current_run = write_minimal_run(root, "current-v2", "mm_run_v0.2", "2026-06-17", gate_counts=True)
            write_live_forward_gate(old_run, "old-v1", "2026-06-16")
            gate = write_live_forward_gate(current_run, "current-v2", "2026-06-17")

            eligibility = run_folder_eligibility(current_run)
            payload = build_paper_payload(
                runs_root=runs_root,
                snapshots_root=root / "snapshots",
                backtest_root=root / "backtest",
                run_folders=[old_run, current_run],
                config={"quote_ttl_seconds": 120.0},
                now="2026-06-17T17:00:00+00:00",
            )
            payload, _known_edge = write_outputs(
                payload,
                json_out=root / "backtest" / "mm_paper_report.json",
                report_out=root / "backtest" / "mm_paper_report.md",
                fills_out=root / "backtest" / "mm_paper_fills_long.csv",
                known_edge_out=root / "backtest" / "mm_known_edge_map.json",
                known_edge_report_out=root / "backtest" / "mm_known_edge_map.md",
            )
            evidence = payload["summary"]["per_market_live_forward_evidence"]
            report = (root / "backtest" / "mm_paper_report.md").read_text(encoding="utf-8")

        self.assertFalse(gate["counts_toward_live_forward_gate"])
        self.assertFalse(eligibility["live_forward_gate_counts"])
        self.assertEqual(eligibility["per_market_evidence_summary"]["model_review_evidence"]["countable_market_count"], 11)
        self.assertEqual(evidence["model_review_evidence"]["countable_market_count"], 11)
        self.assertEqual(evidence["paper_trading_evidence"]["countable_market_count"], 11)
        self.assertEqual(evidence["live_trade_permission_evidence"]["countable_market_count"], 0)
        self.assertFalse(evidence["paper_trading_evidence"]["all_selected_markets_count"])
        self.assertEqual(evidence["model_review_evidence"]["first_blocked_market"], "nyc")
        self.assertEqual(evidence["model_review_evidence"]["first_blocked_gate"], "model_freshness")
        self.assertEqual(payload["summary"]["anti_overfit"]["live_forward_days"], [])
        self.assertEqual(len(payload["per_market_evidence_credits"]), len(LIVE_FORWARD_MARKETS) * 3)
        self.assertEqual({row["run_id"] for row in payload["per_market_evidence_credits"]}, {"current-v2"})
        nyc_rows = [
            row for row in payload["per_market_evidence_credits"]
            if row["market_id"] == "nyc" and row["evidence_class"] == "model_review_evidence"
        ]
        self.assertEqual(nyc_rows[0]["stale_recovery"]["status"], "queued_before_next_tick")
        self.assertIn("suggested_command", nyc_rows[0])
        self.assertIn("## Per-Market Live-Forward Evidence", report)

    def test_per_market_summary_ignores_recovered_stale_rows_for_first_blocked_market(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root, stale_run = write_minimal_run(root, "stale-v2", "mm_run_v0.2", "2026-06-17", gate_counts=True)
            _runs_root, fresh_run = write_minimal_run(root, "fresh-v2", "mm_run_v0.2", "2026-06-17", gate_counts=True)
            write_live_forward_gate(stale_run, "stale-v2", "2026-06-17", stale_market="nyc")
            write_live_forward_gate(fresh_run, "fresh-v2", "2026-06-17", stale_market=None)

            payload = build_paper_payload(
                runs_root=runs_root,
                snapshots_root=root / "snapshots",
                backtest_root=root / "backtest",
                run_folders=[stale_run, fresh_run],
                config={"quote_ttl_seconds": 120.0},
                now="2026-06-17T17:00:00+00:00",
            )
            evidence = payload["summary"]["per_market_live_forward_evidence"]

        self.assertEqual(evidence["model_review_evidence"]["countable_market_count"], 12)
        self.assertEqual(evidence["model_review_evidence"]["blocked_market_count"], 0)
        self.assertIsNone(evidence["model_review_evidence"]["first_blocked_market"])
        self.assertTrue(evidence["model_review_evidence"]["all_selected_markets_count"])


if __name__ == "__main__":
    unittest.main()
