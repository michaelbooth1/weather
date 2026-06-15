import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from market_making_run import build_run_once


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


class TestMarketMakingRun(unittest.TestCase):
    def test_shadow_run_writes_complete_artifacts_and_budget_exhaustion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
            status = root / "observation_status.json"
            write_observation_status(status)

            payload = build_run_once(
                TARGET_DATE,
                5.0,
                mode="shadow",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                observation_status_path=status,
                run_id="run-1",
                now=NOW,
            )

            run_folder = Path(payload["run_folder"])
            for name in [
                "run_config.json",
                "preflight.json",
                "quote_intents_long.csv",
                "budget_ledger.jsonl",
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

    def test_stale_watcher_fails_closed_as_stale_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
            status = root / "observation_status.json"
            write_observation_status(status, heartbeat="2026-06-14T15:00:00+00:00")

            payload = build_run_once(
                TARGET_DATE,
                25.0,
                mode="shadow",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                observation_status_path=status,
                run_id="run-stale",
                now=NOW,
            )

            self.assertEqual(payload["quote_permission_rows"], 0)
            self.assertEqual(payload["live_trade_permission_rows"], 0)
            rows = read_csv(Path(payload["quote_intents_path"]))
            self.assertEqual({row["reason_code"] for row in rows}, {"NO_QUOTE_STALE_INPUT"})
            self.assertEqual({row["orchestrator_reason_code"] for row in rows}, {"stale_input"})

    def test_append_run_carries_budget_reserved_forward(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
            status = root / "observation_status.json"
            write_observation_status(status)

            first = build_run_once(
                TARGET_DATE,
                5.0,
                mode="paper-live-forward",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                observation_status_path=status,
                run_id="paper-run",
                now=NOW,
            )
            second = build_run_once(
                TARGET_DATE,
                5.0,
                mode="paper-live-forward",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                observation_status_path=status,
                run_id="paper-run",
                now=NOW,
                append=True,
            )

            self.assertEqual(first["reason_counts"]["QUOTE_HARVEST_MID"], 1)
            self.assertEqual(second["quote_permission_rows"], 0)
            self.assertEqual(second["reason_counts"]["NO_QUOTE_BUDGET_EXHAUSTED"], 2)
            rows = read_csv(Path(second["quote_intents_path"]))
            self.assertEqual(len(rows), 4)
            budget_events = [
                json.loads(line)
                for line in (Path(second["run_folder"]) / "budget_ledger.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertLessEqual(max(float(row.get("reserved_usdc") or 0.0) for row in budget_events), 5.0)

    def test_missing_target_folder_keeps_selected_market_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = root / "snapshots"
            snapshots_root.mkdir()
            promotion = root / "promotion.json"
            promotion.write_text(json.dumps({"decisions": {"markets": []}}), encoding="utf-8")
            status = root / "observation_status.json"
            write_observation_status(status)

            payload = build_run_once(
                TARGET_DATE,
                25.0,
                mode="shadow",
                markets=["toronto"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
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


if __name__ == "__main__":
    unittest.main()
