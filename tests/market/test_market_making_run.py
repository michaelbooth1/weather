import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from market_making_run import (
    build_run_once,
    lifecycle_summary,
    load_data_layer_live_gate,
    load_open_lifecycle_orders,
    utc_now,
)


NOW = "2026-06-14T16:00:00+00:00"
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


def write_market_fixture(root, stale_book=False):
    snapshots_root = root / "snapshots"
    folder = snapshots_root / "highest-temperature-in-atlanta-on-june-14-2026"
    folder.mkdir(parents=True)
    snapshot_time = "2026-06-14T15:59:30+00:00"
    book_time = "2026-06-14T15:59:20+00:00" if not stale_book else "2026-06-14T15:00:00+00:00"
    snapshot_rows = []
    clob_rows = []
    token_rows = []
    book_rows = []
    for value in (80, 82):
        label = f"{value}-{value + 1} F"
        token = f"token-{value}"
        snapshot_rows.append({
            "snapshot_id": "s1",
            "captured_at_utc": snapshot_time,
            "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
            "model_version": "candidate",
            "range_label": label,
            "condition_id": f"condition-{value}",
            "clob_yes_token_id": token,
            "bin_kind": "eq",
            "bin_value_c": str(value),
            "model_probability": "0.51",
            "market_yes": "0.50",
            "best_bid": "0.49",
            "best_ask": "0.51",
            "market_status": "active",
        })
        clob_rows.append({
            "snapshot_id": "s1",
            "captured_at_utc": snapshot_time,
            "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
            "market_id": "atlanta",
            "range_label": label,
            "bin_kind": "eq",
            "bin_value": str(value),
            "bin_value_hi": str(value + 1),
            "clob_token_id": token,
            "clob_book_captured_at_utc": book_time,
            "clob_feature_available": "1.0",
            "clob_book_age_seconds": "10.0" if not stale_book else "3570.0",
            "clob_midpoint": "0.50",
            "clob_spread": "0.02",
            "clob_best_bid": "0.49",
            "clob_best_ask": "0.51",
            "clob_depth_1pct_total": "100.0",
        })
        token_rows.append({
            "captured_at_utc": book_time,
            "captured_at_local": book_time,
            "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
            "event_title": "Atlanta high",
            "market_id": "atlanta",
            "polymarket_url": "https://polymarket.com/event/highest-temperature-in-atlanta-on-june-14-2026",
            "polymarket_market_id": f"pm-{value}",
            "condition_id": f"condition-{value}",
            "question": label,
            "range_label": label,
            "bin_kind": "eq",
            "bin_value": str(value),
            "bin_value_hi": str(value + 1),
            "unit": "F",
            "outcome": "yes",
            "outcome_index": "0",
            "clob_token_id": token,
            "enable_order_book": "true",
            "active": "true",
            "closed": "false",
            "gamma_yes": "0.50",
            "gamma_no": "0.50",
            "gamma_outcome_price": "",
            "gamma_best_bid": "0.49",
            "gamma_best_ask": "0.51",
            "gamma_last_trade_price": "",
            "gamma_volume": "1000",
            "gamma_liquidity": "1000",
        })
        book_rows.append({
            "capture_id": f"book-{value}",
            "captured_at_utc": book_time,
            "captured_at_local": book_time,
            "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
            "market_id": "atlanta",
            "polymarket_market_id": f"pm-{value}",
            "condition_id": f"condition-{value}",
            "range_label": label,
            "bin_kind": "eq",
            "bin_value": str(value),
            "bin_value_hi": str(value + 1),
            "unit": "F",
            "outcome": "yes",
            "clob_token_id": token,
            "order_book_hash": f"hash-{value}",
            "book_timestamp": "",
            "book_time_utc": book_time,
            "min_order_size": "5",
            "tick_size": "0.001",
            "neg_risk": "true",
            "bid_count": "1",
            "ask_count": "1",
            "best_bid": "0.49",
            "best_ask": "0.51",
            "spread": "0.02",
            "midpoint": "0.50",
            "bid_size_at_best": "20",
            "ask_size_at_best": "20",
            "bid_depth_1pct": "50",
            "ask_depth_1pct": "50",
            "bid_depth_5pct": "100",
            "ask_depth_5pct": "100",
            "bid_depth_all": "200",
            "ask_depth_all": "200",
            "imbalance_1pct": "0",
            "imbalance_5pct": "0",
            "last_trade_price": "",
            "gamma_best_bid": "0.49",
            "gamma_best_ask": "0.51",
            "gamma_last_trade_price": "",
        })
    write_csv(folder / "snapshots_long.csv", list(snapshot_rows[0].keys()), snapshot_rows)
    write_csv(folder / "clob_features_long.csv", list(clob_rows[0].keys()), clob_rows)
    write_csv(folder / "clob_tokens.csv", list(token_rows[0].keys()), token_rows)
    write_csv(folder / "order_books_summary.csv", list(book_rows[0].keys()), book_rows)
    write_csv(
        folder / "source_status_long.csv",
        [
            "snapshot_id",
            "captured_at_utc",
            "captured_at_local",
            "event_slug",
            "model_version",
            "source",
            "ok",
            "status",
            "stale",
            "fetched_at",
            "age_minutes",
            "ttl_minutes",
            "latency_ms",
            "payload_hash",
            "row_count",
            "source_url",
            "error",
        ],
        [{
            "snapshot_id": "s1",
            "captured_at_utc": snapshot_time,
            "captured_at_local": snapshot_time,
            "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
            "model_version": "candidate",
            "source": "wu_current",
            "ok": "true",
            "status": "fresh",
            "stale": "false",
            "fetched_at": snapshot_time,
            "age_minutes": "0.5",
            "ttl_minutes": "90",
            "latency_ms": "10",
            "payload_hash": "abc",
            "row_count": "1",
            "source_url": "",
            "error": "",
        }],
    )
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
    return snapshots_root, promotion


def write_observation_status(path, heartbeat="2026-06-14T15:59:50+00:00"):
    path.write_text(json.dumps({
        "last_heartbeat": heartbeat,
        "consecutive_errors": 0,
    }), encoding="utf-8")


def write_known_edge_map(path, permission="harvest_only", reason="promotion_shadow"):
    path.write_text(json.dumps({
        "schema_version": "mm_known_edge_map_v0.1",
        "records": [{
            "market_id": "atlanta",
            "cutoff": "*",
            "hour_utc": "*",
            "band_distance_bucket": "*",
            "band_type": "*",
            "casebook_taxonomy": "*",
            "regime": "*",
            "source_fresh": "*",
            "book_imbalance_bucket": "*",
            "permission": permission,
            "reason": reason,
        }],
        "summary": {"record_count": 1},
    }), encoding="utf-8")
    return path


def write_live_readiness(path):
    path.write_text(json.dumps({
        "account_platform_verified": True,
        "wallet_ready": True,
        "allowance_ready": True,
        "heartbeat_ready": True,
        "user_websocket_ready": True,
        "cancel_all_ready": True,
    }), encoding="utf-8")
    return path


def write_data_layer_audit(path, ok=True):
    path.write_text(json.dumps({
        "schema_version": "data_layer_audit_v0.3",
        "generated_at_utc": NOW,
        "gate_summary": {"status": "PASS" if ok else "FAIL"},
        "snapshots": {
            "has_market_token_ids": ok,
            "clob_features": {
                "row_count": 2 if ok else 0,
                "book_available_rows": 2 if ok else 0,
            },
            "folders": [{
                "target_date": TARGET_DATE,
                "rows_with_market_token_ids": 2 if ok else 0,
                "artifact_presence": {"clob_features": ok},
                "clob_features": {"book_available_rows": 2 if ok else 0},
            }],
        },
    }), encoding="utf-8")
    return path


class TestMarketMakingRun(unittest.TestCase):
    def test_data_layer_live_gate_requires_target_day_clob_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = write_data_layer_audit(root / "good.json", ok=True)
            bad = write_data_layer_audit(root / "bad.json", ok=False)

            good_gate = load_data_layer_live_gate(good, TARGET_DATE, "live-pilot")
            bad_gate = load_data_layer_live_gate(bad, TARGET_DATE, "live-pilot")

        self.assertTrue(good_gate["ok"])
        self.assertFalse(bad_gate["ok"])
        self.assertIn("has_market_token_ids", bad_gate["missing"])
        self.assertFalse(load_data_layer_live_gate(bad, TARGET_DATE, "shadow")["required"])

    def test_live_pilot_blocks_when_latest_data_layer_audit_lacks_clob_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
            status = root / "observation_status.json"
            write_observation_status(status)
            known_edge = write_known_edge_map(root / "known_edge.json")
            live_readiness = write_live_readiness(root / "live_readiness.json")
            bad_audit = write_data_layer_audit(root / "bad_data_layer_audit.json", ok=False)

            payload = build_run_once(
                TARGET_DATE,
                25.0,
                mode="live-pilot",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                observation_status_path=status,
                run_id="live-blocked",
                now=NOW,
                pilot=True,
                confirm_live_orders=True,
                live_readiness_path=live_readiness,
                data_layer_audit_path=bad_audit,
            )

            preflight = json.loads(Path(payload["preflight_path"]).read_text(encoding="utf-8"))
            gates = {
                gate["name"]: gate
                for gate in preflight["markets"][0]["gates"]
            }

        self.assertEqual(payload["preflight_status"], "BLOCK")
        self.assertEqual(payload["quote_permission_rows"], 0)
        self.assertFalse(preflight["data_layer_live_gate"]["ok"])
        self.assertFalse(gates["data_layer_live_gate"]["ok"])
        self.assertIn("data-layer audit missing live CLOB proof", gates["data_layer_live_gate"]["detail"])

    def test_shadow_run_writes_complete_artifacts_and_budget_exhaustion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
            status = root / "observation_status.json"
            write_observation_status(status)
            known_edge = write_known_edge_map(root / "known_edge.json")

            payload = build_run_once(
                TARGET_DATE,
                5.0,
                mode="shadow",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                observation_status_path=status,
                run_id="run-1",
                now=NOW,
            )

            run_folder = Path(payload["run_folder"])
            for name in [
                "run_config.json",
                "preflight.json",
                "preflight_remediation.json",
                "quote_intents_long.csv",
                "budget_ledger.jsonl",
                "order_lifecycle.jsonl",
                "risk_events.jsonl",
                "fills_long.csv",
                "run_report.md",
            ]:
                self.assertTrue((run_folder / name).exists(), name)
            self.assertEqual(payload["row_count"], 2)
            self.assertEqual(payload["live_trade_permission_rows"], 0)
            self.assertEqual(payload["reason_counts"]["QUOTE_HARVEST_MID"], 1)
            self.assertEqual(payload["reason_counts"]["NO_QUOTE_BUDGET_EXHAUSTED"], 1)
            rows = read_csv(run_folder / "quote_intents_long.csv")
            self.assertEqual({row["run_id"] for row in rows}, {"run-1"})
            self.assertTrue(all(row["live_trade_permission"] in {"False", "False"} for row in rows))
            budget_events = [
                json.loads(line)
                for line in (run_folder / "budget_ledger.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            max_reserved = max(float(row.get("reserved_usdc") or 0.0) for row in budget_events)
            self.assertLessEqual(max_reserved, 5.0)
            self.assertIn("order_lifecycle", payload)
            self.assertGreaterEqual(payload["order_lifecycle"]["posted_this_tick_count"], 1)

    def test_stale_watcher_fails_closed_as_stale_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
            status = root / "observation_status.json"
            write_observation_status(status, heartbeat="2026-06-14T15:00:00+00:00")
            known_edge = write_known_edge_map(root / "known_edge.json")

            payload = build_run_once(
                TARGET_DATE,
                25.0,
                mode="shadow",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                observation_status_path=status,
                run_id="run-stale",
                now=NOW,
            )

            self.assertEqual(payload["quote_permission_rows"], 0)
            self.assertEqual(payload["live_trade_permission_rows"], 0)
            rows = read_csv(Path(payload["quote_intents_path"]))
            self.assertEqual({row["reason_code"] for row in rows}, {"NO_QUOTE_STALE_INPUT"})
            self.assertEqual({row["orchestrator_reason_code"] for row in rows}, {"stale_input"})

    def test_append_same_tick_does_not_double_reserve_existing_lifecycle_orders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
            status = root / "observation_status.json"
            write_observation_status(status)
            known_edge = write_known_edge_map(root / "known_edge.json")

            first = build_run_once(
                TARGET_DATE,
                25.0,
                mode="paper-live-forward",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                observation_status_path=status,
                run_id="paper-run",
                now=NOW,
            )
            second = build_run_once(
                TARGET_DATE,
                25.0,
                mode="paper-live-forward",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                observation_status_path=status,
                run_id="paper-run",
                now=NOW,
                append=True,
            )

            self.assertEqual(first["reason_counts"]["QUOTE_HARVEST_MID"], 2)
            self.assertEqual(second["quote_permission_rows"], 2)
            self.assertEqual(second["budget_reserved_usdc"], first["budget_reserved_usdc"])
            self.assertEqual(second["order_lifecycle"]["posted_this_tick_count"], 0)
            rows = read_csv(Path(second["quote_intents_path"]))
            self.assertEqual(len(rows), 4)
            budget_events = [
                json.loads(line)
                for line in (Path(second["run_folder"]) / "budget_ledger.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertLessEqual(max(float(row.get("reserved_usdc") or 0.0) for row in budget_events), 25.0)

    def test_append_new_tick_replaces_quotes_without_budget_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
            status = root / "observation_status.json"
            write_observation_status(status)
            known_edge = write_known_edge_map(root / "known_edge.json")

            first = build_run_once(
                TARGET_DATE,
                25.0,
                mode="paper-live-forward",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                observation_status_path=status,
                run_id="replace-run",
                now=NOW,
            )
            second = build_run_once(
                TARGET_DATE,
                25.0,
                mode="paper-live-forward",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                observation_status_path=status,
                run_id="replace-run",
                now="2026-06-14T16:01:00+00:00",
                append=True,
            )

            self.assertEqual(second["quote_permission_rows"], 2)
            self.assertAlmostEqual(second["budget_reserved_usdc"], first["budget_reserved_usdc"])
            self.assertGreater(second["budget_released_usdc"], 0.0)
            self.assertEqual(second["cumulative_tick_count"], 2)
            self.assertEqual(second["cumulative_quote_permission_rows"], 4)
            self.assertEqual(second["cumulative_paper_posted_count"], 8)
            self.assertEqual(second["cumulative_lifecycle_transition_counts"]["replaced"], 4)
            self.assertEqual(second["latest_tick"]["quote_permission_rows"], 2)
            transitions = [
                json.loads(line)["transition"]
                for line in (Path(second["run_folder"]) / "order_lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertIn("replaced", transitions)

    def test_expired_quotes_release_before_new_reservations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
            status = root / "observation_status.json"
            write_observation_status(status)
            known_edge = write_known_edge_map(root / "known_edge.json")

            first = build_run_once(
                TARGET_DATE,
                25.0,
                mode="paper-live-forward",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                observation_status_path=status,
                run_id="expiry-run",
                now=NOW,
                policy_config={"quote_ttl_seconds": 30.0},
            )
            second = build_run_once(
                TARGET_DATE,
                25.0,
                mode="paper-live-forward",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                observation_status_path=status,
                run_id="expiry-run",
                now="2026-06-14T16:01:00+00:00",
                append=True,
                policy_config={"quote_ttl_seconds": 30.0},
            )

            self.assertAlmostEqual(second["budget_reserved_usdc"], first["budget_reserved_usdc"])
            self.assertGreater(second["budget_released_usdc"], 0.0)
            transitions = [
                json.loads(line)["transition"]
                for line in (Path(second["run_folder"]) / "order_lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertIn("expired", transitions)

    def test_lifecycle_summary_separates_same_market_and_cross_market_risk(self):
        summary = lifecycle_summary(
            {
                "a": {"market_id": "atlanta", "event_slug": "event-atlanta", "remaining_risk_usdc": 4.0},
                "b": {"market_id": "atlanta", "event_slug": "event-atlanta", "remaining_risk_usdc": 3.0},
                "c": {"market_id": "nyc", "event_slug": "event-nyc", "remaining_risk_usdc": 5.0},
            },
            budget=20.0,
            released_events=[],
            posted_events=[],
            now=utc_now(NOW),
        )

        self.assertEqual(summary["reserved_by_market"], {"atlanta": 7.0, "nyc": 5.0})
        self.assertEqual(summary["reserved_by_event"], {"event-atlanta": 7.0, "event-nyc": 5.0})
        self.assertTrue(summary["platform_balance_semantics"]["polymarket_cross_market_open_orders_may_exceed_wallet_balance"])
        self.assertTrue(summary["platform_balance_semantics"]["same_market_open_orders_still_need_event_level_worst_case_backing"])

    def test_append_releases_open_budget_when_preflight_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
            status = root / "observation_status.json"
            write_observation_status(status)
            known_edge = write_known_edge_map(root / "known_edge.json")

            first = build_run_once(
                TARGET_DATE,
                25.0,
                mode="paper-live-forward",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                observation_status_path=status,
                run_id="release-run",
                now=NOW,
            )
            folder = Path(first["run_folder"])
            (snapshots_root / "highest-temperature-in-atlanta-on-june-14-2026" / "source_status_long.csv").unlink()

            second = build_run_once(
                TARGET_DATE,
                25.0,
                mode="paper-live-forward",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                observation_status_path=status,
                run_id="release-run",
                now="2026-06-14T16:01:00+00:00",
                append=True,
            )

            self.assertGreater(first["budget_reserved_usdc"], 0.0)
            self.assertEqual(second["quote_permission_rows"], 0)
            self.assertEqual(second["budget_reserved_usdc"], 0.0)
            self.assertGreater(second["budget_released_usdc"], 0.0)
            transitions = [
                json.loads(line)["transition"]
                for line in (folder / "order_lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertIn("blocked_by_preflight", transitions)

    def test_cancel_all_flag_releases_and_prevents_reposting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
            status = root / "observation_status.json"
            write_observation_status(status)
            known_edge = write_known_edge_map(root / "known_edge.json")

            first = build_run_once(
                TARGET_DATE,
                25.0,
                mode="paper-live-forward",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                observation_status_path=status,
                run_id="cancel-run",
                now=NOW,
            )
            folder = Path(first["run_folder"])
            (folder / "cancel_all.flag").write_text("1", encoding="utf-8")

            second = build_run_once(
                TARGET_DATE,
                25.0,
                mode="paper-live-forward",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                observation_status_path=status,
                run_id="cancel-run",
                now="2026-06-14T16:01:00+00:00",
                append=True,
            )

            self.assertEqual(second["quote_permission_rows"], 0)
            self.assertEqual(second["reason_counts"]["NO_QUOTE_CANCEL_ALL"], 2)
            self.assertEqual(second["budget_reserved_usdc"], 0.0)
            transitions = [
                json.loads(line)["transition"]
                for line in (folder / "order_lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertIn("canceled", transitions)

    def test_partial_fill_lifecycle_event_reduces_open_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "order_lifecycle.jsonl"
            opened = {
                "transition": "paper_posted",
                "lifecycle_key": "k1",
                "run_id": "r1",
                "market_id": "atlanta",
                "size": 10.0,
                "remaining_size": 10.0,
                "open_risk_usdc": 5.0,
                "remaining_risk_usdc": 5.0,
            }
            fill = {
                "transition": "filled",
                "lifecycle_key": "k1",
                "fill_size": 4.0,
                "generated_at_utc": "2026-06-14T16:02:00+00:00",
            }
            path.write_text("\n".join(json.dumps(row) for row in [opened, fill]) + "\n", encoding="utf-8")

            open_orders = load_open_lifecycle_orders(path)

            self.assertEqual(set(open_orders), {"k1"})
            self.assertAlmostEqual(float(open_orders["k1"]["remaining_size"]), 6.0)
            self.assertAlmostEqual(float(open_orders["k1"]["remaining_risk_usdc"]), 3.0)

    def test_preflight_remediation_groups_missing_source_status_and_stale_clob(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root, stale_book=True)
            folder = snapshots_root / "highest-temperature-in-atlanta-on-june-14-2026"
            (folder / "source_status_long.csv").unlink()
            status = root / "observation_status.json"
            write_observation_status(status)
            known_edge = write_known_edge_map(root / "known_edge.json")

            payload = build_run_once(
                TARGET_DATE,
                25.0,
                mode="paper-live-forward",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                observation_status_path=status,
                run_id="remediate-run",
                now=NOW,
            )

            remediation = json.loads(Path(payload["preflight_remediation_path"]).read_text(encoding="utf-8"))
            roots = remediation["root_cause_counts"]
            self.assertIn("missing_source_status_row", roots)
            self.assertIn("stale_clob_book_tape", roots)
            self.assertFalse(remediation["counts_toward_live_forward_gate"])
            incidents = remediation["incidents"]
            self.assertTrue(all(row["suggested_command"] for row in incidents))
            risk_events = [
                json.loads(line)
                for line in Path(payload["risk_events_path"]).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(any(row.get("category") == "preflight_remediation" for row in risk_events))

    def test_missing_target_folder_keeps_selected_market_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = root / "snapshots"
            snapshots_root.mkdir()
            promotion = root / "promotion.json"
            promotion.write_text(json.dumps({"decisions": {"markets": []}}), encoding="utf-8")
            status = root / "observation_status.json"
            write_observation_status(status)
            known_edge = root / "missing_known_edge.json"

            payload = build_run_once(
                TARGET_DATE,
                25.0,
                mode="shadow",
                markets=["toronto"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                observation_status_path=status,
                run_id="run-missing",
                now=NOW,
            )

            self.assertEqual(payload["row_count"], 1)
            self.assertEqual(payload["quote_permission_rows"], 0)
            rows = read_csv(Path(payload["quote_intents_path"]))
            self.assertEqual(rows[0]["market_id"], "toronto")
            self.assertEqual(rows[0]["event_slug"], "highest-temperature-in-toronto-on-june-14-2026")
            self.assertEqual(rows[0]["reason_code"], "NO_QUOTE_MISSING_PREFLIGHT")

    def test_known_edge_no_quote_record_blocks_orchestrated_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
            status = root / "observation_status.json"
            write_observation_status(status)
            known_edge = write_known_edge_map(
                root / "known_edge.json",
                permission="no_quote",
                reason="promotion_block",
            )

            payload = build_run_once(
                TARGET_DATE,
                25.0,
                mode="shadow",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                observation_status_path=status,
                run_id="run-known-edge-block",
                now=NOW,
            )

            self.assertEqual(payload["quote_permission_rows"], 0)
            self.assertEqual(payload["reason_counts"]["NO_QUOTE_KNOWN_EDGE_PERMISSION"], 2)
            rows = read_csv(Path(payload["quote_intents_path"]))
            self.assertEqual({row["known_edge_permission"] for row in rows}, {"no_quote"})
            self.assertEqual({row["known_edge_reason"] for row in rows}, {"promotion_block"})


if __name__ == "__main__":
    unittest.main()
