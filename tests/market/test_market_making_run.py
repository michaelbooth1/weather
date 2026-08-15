import csv
import json
import os
import sys
import tempfile
import unittest
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from weather.market import market_making_run
from weather.market.market_making_run import (
    build_useful_work_liveness,
    build_run_once,
    format_run_cli_summary,
    lifecycle_summary,
    load_data_layer_live_gate,
    load_open_lifecycle_orders,
    load_platform_verification_gate,
    paper_until_utc,
    runtime_identity_snapshot,
    utc_now,
)
from weather.market.live_forward_gate import build_live_forward_gate
from weather.market.market_making_evidence import EVIDENCE_MODE_ACTIVE_DAY
from weather.market.market_making_model_variants import build_model_variant_quote_rows
from weather.market.market_making_preflight import (
    build_preflight_remediation,
    platform_account_snapshot_sha256,
    stage1_lifecycle_bundle_sha256,
)
from weather.market.market_making_run_support import preflight_book_audit, read_csv_rows
from weather.market.market_making_run_support import classify_zero_trade_root_cause, preflight_market
from weather.market.market_making_run_support import source_status_degradation_preflight
from weather.market.mm_geoblock import collect_official_geoblock_evidence
from weather.market.market_config import config_for_date
from weather.market.market_registry import spec_for_id
from weather.operations.market_making_preflight_recovery import close_out_preflight_recovery
from weather.runtime_identity import get_runtime_identity


NOW = "2026-06-14T16:00:00+00:00"
TARGET_DATE = "2026-06-14"


def eligible_geoblock(now=NOW):
    class Response:
        status = 200

        def read(self, _limit):
            return json.dumps({
                "blocked": False,
                "country": "CH",
                "region": "ZH",
                "ip": "203.0.113.8",
            }).encode("utf-8")

        def close(self):
            pass

    return collect_official_geoblock_evidence(
        opener=lambda _request, timeout: Response(),
        proxy_detector=lambda: {},
        now=now,
    )


def synthetic_stage1_lifecycle_bundle(requested_budget_usdc=25.0):
    bootstrap_sha256 = "a" * 64

    def result(mode, order_id):
        return {
            "schema_version": "mm_live_lifecycle_probe_v0.1",
            "status": "PASS",
            "completed_at_utc": NOW,
            "platform": "polymarket_global",
            "settlement_unit": "pUSD",
            "cancellation_mode": mode,
            "bootstrap_schema_version": "mm_platform_bootstrap_v0.1",
            "bootstrap_sha256": bootstrap_sha256,
            "condition_id": "0x" + "b" * 64,
            "token_id": "12345",
            "heartbeat_id_acknowledged": True,
            "starting_zero_open_orders_verified": True,
            "starting_zero_positions_verified": True,
            "order_notional_usdc": 0.05,
            "order_id": order_id,
            "placement_status": "live",
            "geoblock_country": "CH",
            "geoblock_region": "ZH",
            "capability_geoblock_evidence_sha256": "c" * 64,
            "submission_geoblock_evidence_sha256": "d" * 64,
            "open_order_observed": True,
            "authoritative_user_event_observed": True,
            "cancellation_observed": True,
            "cancellation_elapsed_seconds": 0 if mode == "cancel_all" else 15,
            "terminal_user_event_observed": True,
            "no_trade_lifecycle_event_observed": True,
            "cancel_response_present": mode == "cancel_all",
            "zero_open_orders_verified": True,
            "zero_positions_verified": True,
            "secret_values_redacted": True,
            "journal_path": f"stage1-{mode}.jsonl",
            "journal_sha256": ("e" if mode == "cancel_all" else "f") * 64,
        }

    bundle = {
        "schema_version": "mm_stage1_lifecycle_bundle_v0.1",
        "status": "PASS",
        "created_at_utc": NOW,
        "platform": "polymarket_global",
        "settlement_unit": "pUSD",
        "bootstrap_schema_version": "mm_platform_bootstrap_v0.1",
        "bootstrap_sha256": bootstrap_sha256,
        "condition_id": "0x" + "b" * 64,
        "token_id": "12345",
        "funder_address": "0x0000000000000000000000000000000000000001",
        "requested_budget_usdc": requested_budget_usdc,
        "geoblock_country": "CH",
        "geoblock_region": "ZH",
        "lifecycle_results": {
            "cancel_all": result("cancel_all", "cancel-order"),
            "dead_man": result("dead_man", "dead-man-order"),
        },
        "journal_evidence": {
            "cancel_all": {"sha256": "e" * 64, "row_count": 12},
            "dead_man": {"sha256": "f" * 64, "row_count": 12},
        },
        "derived_platform_evidence": {
            "starting_open_orders_rest_verified": True,
            "order_update_verified": True,
            "fill_event_verified": False,
            "no_fill_lifecycle_verified": True,
            "final_state_reconciliation_verified": True,
            "cancel_all_request_verified": True,
            "cancel_all_zero_open_orders_verified": True,
            "dead_man_automatic_cancel_verified": True,
            "heartbeat_acknowledgment_verified": True,
        },
        "secret_values_redacted": True,
    }
    bundle["bundle_sha256"] = stage1_lifecycle_bundle_sha256(bundle)
    return bundle


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_support_read_csv_rows_tolerates_legacy_degree_byte():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "order_books_summary.csv"
        path.write_bytes(b"range_label,bin_kind,bin_value\n\xb0F,eq,94\n")

        rows = read_csv_rows(path)

    assert rows[0]["range_label"] == "\u00b0F"
    assert rows[0]["_csv_encoding_status"] == "legacy_encoding"
    assert rows[0]["_csv_source_encoding"] == "cp1252"
    assert rows[0]["bin_value"] == "94"


def test_run_cli_summary_separates_intents_permissions_and_no_quotes():
    line = format_run_cli_summary(
        {
            "quote_intent_rows": 132,
            "quote_rows": 132,
            "no_quote_rows": 132,
            "quote_permission_rows": 0,
            "live_trade_permission_rows": 0,
            "preflight_status": "BLOCK",
            "run_folder": "data/mm_runs/example",
        }
    )

    assert "132 quote-intent rows" in line
    assert "0 quote-permission rows" in line
    assert "132 no-quote rows" in line
    assert "0 live-permission rows" in line
    assert "0 quote rows" not in line


def test_paper_loop_default_cutoff_freezes_at_20_toronto_not_market_midnights():
    cutoff = paper_until_utc("2026-06-16", [spec_for_id("los-angeles")])

    assert cutoff == datetime(2026, 6, 17, 0, 0, tzinfo=timezone.utc)


def test_paper_loop_does_not_start_a_tick_at_the_20_toronto_cutoff():
    cutoff = datetime(2026, 6, 17, 0, 0, tzinfo=timezone.utc)
    with patch.object(market_making_run, "utc_now", return_value=cutoff), patch.object(
        market_making_run,
        "keep_system_awake",
        return_value=nullcontext(),
    ), patch.object(
        market_making_run,
        "build_run_once",
        side_effect=AssertionError("post-window tick must not start"),
    ):
        result = market_making_run.run_loop(
            "2026-06-16",
            500,
            "paper-live-forward",
            markets=["toronto"],
        )

    assert result is None


def test_preflight_book_audit_uses_clob_startup_gap_policy():
    now = datetime(2026, 6, 16, 14, 0, tzinfo=timezone.utc)
    rows = [
        {"captured_at_utc": "2026-06-16T13:00:00+00:00", "clob_token_id": "yes-1"},
        {"captured_at_utc": "2026-06-16T13:20:00+00:00", "clob_token_id": "yes-1"},
        {"captured_at_utc": "2026-06-16T13:53:00+00:00", "clob_token_id": "yes-1"},
        {"captured_at_utc": "2026-06-16T13:55:30+00:00", "clob_token_id": "yes-1"},
        {"captured_at_utc": "2026-06-16T13:57:00+00:00", "clob_token_id": "yes-1"},
        {"captured_at_utc": "2026-06-16T13:59:30+00:00", "clob_token_id": "yes-1"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        write_csv(folder / "order_books_summary.csv", list(rows[0].keys()), rows)

        result = preflight_book_audit(
            folder,
            now=now,
            max_gap_seconds=120,
            loop_status={
                "started_at": "2026-06-16T13:52:00+00:00",
                "last_iteration_elapsed_seconds": 80,
                "last_sleep_seconds": 15,
            },
        )

    assert result["ok"]
    assert result["gaps_over_threshold"] == 0
    assert result["startup_gaps_ignored"] == 2
    assert result["ignored_gap_cutoff_utc"] == "2026-06-16T13:55:00+00:00"


def test_preflight_book_audit_ignores_only_gaps_ending_before_maker_window():
    now = datetime(2026, 6, 16, 11, 6, tzinfo=timezone.utc)
    active_start = datetime(2026, 6, 16, 11, 0, tzinfo=timezone.utc)
    pre_window_rows = [
        {"captured_at_utc": "2026-06-16T09:00:00+00:00", "clob_token_id": "yes-1"},
        {"captured_at_utc": "2026-06-16T10:59:00+00:00", "clob_token_id": "yes-1"},
        {"captured_at_utc": "2026-06-16T11:00:30+00:00", "clob_token_id": "yes-1"},
        {"captured_at_utc": "2026-06-16T11:01:30+00:00", "clob_token_id": "yes-1"},
        {"captured_at_utc": "2026-06-16T11:02:30+00:00", "clob_token_id": "yes-1"},
        {"captured_at_utc": "2026-06-16T11:03:30+00:00", "clob_token_id": "yes-1"},
        {"captured_at_utc": "2026-06-16T11:04:30+00:00", "clob_token_id": "yes-1"},
        {"captured_at_utc": "2026-06-16T11:05:30+00:00", "clob_token_id": "yes-1"},
    ]
    in_window_rows = [
        {"captured_at_utc": "2026-06-16T10:59:30+00:00", "clob_token_id": "yes-1"},
        {"captured_at_utc": "2026-06-16T11:00:00+00:00", "clob_token_id": "yes-1"},
        {"captured_at_utc": "2026-06-16T11:05:00+00:00", "clob_token_id": "yes-1"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        before = root / "before"
        inside = root / "inside"
        before.mkdir()
        inside.mkdir()
        write_csv(before / "order_books_summary.csv", list(pre_window_rows[0]), pre_window_rows)
        write_csv(inside / "order_books_summary.csv", list(in_window_rows[0]), in_window_rows)
        ignored = preflight_book_audit(
            before,
            now=now,
            max_gap_seconds=120,
            loop_status={},
            active_window_start_utc=active_start,
        )
        counted = preflight_book_audit(
            inside,
            now=now,
            max_gap_seconds=120,
            loop_status={},
            active_window_start_utc=active_start,
        )

    assert ignored["ok"]
    assert ignored["gaps_over_threshold"] == 0
    assert ignored["ignored_gap_cutoff_utc"] == active_start.isoformat()
    assert ignored["maker_active_window_start_utc"] == active_start.isoformat()
    assert counted["ok"] is False
    assert counted["gaps_over_threshold"] == 1
    assert counted["max_counted_gap_seconds"] == 300.0


def test_event_metadata_gate_blocks_maker_preflight_as_market_discovery():
    now = datetime(2026, 6, 14, 16, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        write_csv(
            folder / "clob_tokens.csv",
            ["clob_token_id", "outcome", "condition_id", "active", "closed"],
            [{"clob_token_id": "yes-token", "outcome": "Yes", "condition_id": "condition-1", "active": "true", "closed": "false"}],
        )
        write_csv(
            folder / "order_books_summary.csv",
            ["captured_at_utc", "clob_token_id", "midpoint"],
            [{"captured_at_utc": now.isoformat(), "clob_token_id": "yes-token", "midpoint": "0.5"}],
        )
        row = preflight_market(
            spec_for_id("atlanta"),
            config_for_date("2026-06-14", "atlanta"),
            folder,
            [{"snapshot_id": "s1", "captured_at_utc": now.isoformat(), "market_status": "active"}],
            [{"captured_at_utc": now.isoformat(), "ok": "true", "status": "fresh"}],
            [{"captured_at_utc": now.isoformat(), "clob_token_id": "yes-token", "midpoint": "0.5", "min_order_size": "5", "tick_size": "0.01"}],
            [{"snapshot_id": "s1", "range_label": "80-81"}],
            {"promotion_state": "PAPER", "action": "paper"},
            {"fresh": True, "reason": "ok"},
            now,
            "paper",
            {
                "max_book_age_seconds": 300,
                "max_model_age_seconds": 300,
                "max_watcher_age_seconds": 300,
            },
            event_metadata_gate={
                "required": True,
                "ok": False,
                "reason": "target event missing from generated metadata",
            },
        )

    assert row["status"] == "BLOCK"
    assert row["first_failing_gate"]["name"] == "event_metadata_validation"
    diagnosis = classify_zero_trade_root_cause([row], permission_rows=0, output_rows=1)
    assert diagnosis["root_cause_class"] == "blocked_by_market_discovery"


def test_live_pilot_preflight_requires_a_production_capable_release():
    now = datetime(2026, 6, 14, 16, 0, tzinfo=timezone.utc)
    policy = {
        "max_book_age_seconds": 300,
        "max_model_age_seconds": 300,
        "max_watcher_age_seconds": 300,
    }
    platform_gate = {"required": True, "ok": True}
    common = {
        "live_ready": True,
        "live_confirmed": True,
        "pilot": True,
        "platform_verification_gate": platform_gate,
    }
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        blocked = preflight_market(
            spec_for_id("atlanta"),
            config_for_date("2026-06-14", "atlanta"),
            folder,
            [],
            [],
            [],
            [],
            {"promotion_state": "PAPER", "action": "paper"},
            {"fresh": True, "reason": "ok"},
            now,
            "live-pilot",
            policy,
            release_production_capable=False,
            **common,
        )
        production = preflight_market(
            spec_for_id("atlanta"),
            config_for_date("2026-06-14", "atlanta"),
            folder,
            [],
            [],
            [],
            [],
            {"promotion_state": "PAPER", "action": "paper"},
            {"fresh": True, "reason": "ok"},
            now,
            "live-pilot",
            policy,
            release_production_capable=True,
            **common,
        )

    assert blocked["live_gate"]["release_production_capable"] is False
    assert blocked["live_gate"]["ok"] is False
    assert any(
        "production-capable active release" in reason
        for reason in blocked["blocking_reasons"]
    )
    assert production["live_gate"]["release_production_capable"] is True
    assert production["live_gate"]["ok"] is True


def write_market_fixture(root, stale_book=False, blank_tokens=False, inactive_tokens=False):
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
        token = "" if blank_tokens else f"token-{value}"
        condition = "" if blank_tokens else f"condition-{value}"
        snapshot_rows.append({
            "snapshot_id": "s1",
            "captured_at_utc": snapshot_time,
            "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
            "model_version": "candidate",
            "range_label": label,
            "condition_id": condition,
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
            "condition_id": condition,
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
            "active": "false" if inactive_tokens else "true",
            "closed": "true" if inactive_tokens else "false",
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
            "condition_id": condition,
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


def append_latest_snapshot_without_clob_features(snapshots_root):
    folder = Path(snapshots_root) / "highest-temperature-in-atlanta-on-june-14-2026"
    snapshot_rows = read_csv(folder / "snapshots_long.csv")
    latest_rows = []
    for row in snapshot_rows:
        item = dict(row)
        item["snapshot_id"] = "s2"
        item["captured_at_utc"] = "2026-06-14T15:59:50+00:00"
        latest_rows.append(item)
    write_csv(folder / "snapshots_long.csv", list(snapshot_rows[0].keys()), [*snapshot_rows, *latest_rows])

    source_rows = read_csv(folder / "source_status_long.csv")
    source_latest = []
    for row in source_rows:
        item = dict(row)
        item["snapshot_id"] = "s2"
        item["captured_at_utc"] = "2026-06-14T15:59:50+00:00"
        item["fetched_at"] = "2026-06-14T15:59:50+00:00"
        source_latest.append(item)
    write_csv(folder / "source_status_long.csv", list(source_rows[0].keys()), [*source_rows, *source_latest])
    return folder


def write_observation_status(path, heartbeat="2026-06-14T15:59:50+00:00", market_ledger=None):
    payload = {
        "last_heartbeat": heartbeat,
        "consecutive_errors": 0,
    }
    if market_ledger:
        payload["markets"] = {"atlanta": {"monotonic_high_ledger": market_ledger}}
    path.write_text(json.dumps(payload), encoding="utf-8")


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


def write_data_layer_audit(
    path,
    ok=True,
    raw_clob_artifacts=None,
    raw_book_artifact="order_books_summary",
):
    raw_ok = ok if raw_clob_artifacts is None else raw_clob_artifacts
    artifact_presence = {
        "clob_features": ok,
        "clob_tokens": raw_ok,
    }
    if raw_book_artifact:
        artifact_presence[raw_book_artifact] = raw_ok
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
                "artifact_presence": artifact_presence,
                "clob_features": {"book_available_rows": 2 if ok else 0},
            }],
        },
    }), encoding="utf-8")
    return path


def write_platform_verification(path, ok=True, target_date=TARGET_DATE, verified_at=NOW, platform="polymarket_global"):
    maker_only_field = "participateDontInitiate" if platform == "polymarket_us" else "postOnly"
    account_snapshot = {
        "balance_allowance_verified": True,
        "collateral_balance_usdc": 25.0,
        "collateral_allowance_usdc": 25.0,
        "closed_only_mode_verified": True,
        "closed_only": False,
        "zero_open_orders_verified": True,
        "open_order_count": 0,
        "position_query_exact_scope_verified": True,
        "zero_positions_verified": True,
        "position_count": 0,
        "source_response_sha256": "b" * 64,
    }
    account_snapshot["snapshot_sha256"] = platform_account_snapshot_sha256(
        account_snapshot
    )
    lifecycle_bundle = synthetic_stage1_lifecycle_bundle()
    payload = {
        "schema_version": "mm_platform_verification_v0.4",
        "status": "PASS",
        "verified_at_utc": verified_at,
        "docs_checked_at_utc": verified_at,
        "verified_for_target_date": target_date,
        "platform": platform,
        "international_platform_confirmed": platform == "polymarket_global",
        "physical_location_matches_geoblock_confirmed": platform == "polymarket_global",
        "geoblock_circumvention_absent_confirmed": platform == "polymarket_global",
        "geographic_eligibility": eligible_geoblock(verified_at),
        "eligibility_verified": True,
        "api_base_url": "https://polymarket.com",
        "clob_host": "https://clob.polymarket.com",
        "settlement_unit": "pUSD",
        "wallet_type": "deposit_wallet",
        "signature_type": "POLY_1271",
        "signature_type_id": 3,
        "funder_address": "0x0000000000000000000000000000000000000001",
        "wallet_identity": {
            "private_key_signer_address": "0x0000000000000000000000000000000000000002",
            "order_signer_address": "0x0000000000000000000000000000000000000001",
            "api_key_owner_address": "0x0000000000000000000000000000000000000002",
            "consistency_verified": True,
        },
        "sdk_contract": {
            "distribution": "py-clob-client-v2",
            "version": "1.1.0",
            "exact_version_verified": True,
            "wallet_model_probe_verified": True,
        },
        "allowances_verified": True,
        "balance_verified": True,
        "collateral_balance_usdc": 25.0,
        "collateral_allowance_usdc": 25.0,
        "account_snapshot_sha256": account_snapshot["snapshot_sha256"],
        "open_order_count": 0,
        "account_snapshot": account_snapshot,
        "stage1_lifecycle_bundle_sha256": lifecycle_bundle["bundle_sha256"],
        "stage1_lifecycle_bundle": lifecycle_bundle,
        "fees_verified": True,
        "fee_model": {
            "theta": 0.05,
            "maker_rebate_rate": 0.25,
        },
        "reward_rules_verified": True,
        "rebate_rules_verified": True,
        "order_semantics_verified": True,
        "maker_only_order_field": maker_only_field,
        "maker_only_order_field_verified": True,
        "limit_order_semantics_verified": True,
        "market_order_semantics_verified": True,
        "cancel_semantics_verified": True,
        "tick_size_verified": True,
        "min_order_size_verified": True,
        "user_websocket_verified": True,
        "private_user_stream": {
            "connection_verified": True,
            "starting_open_orders_rest_verified": True,
            "order_update_verified": True,
            "fill_event_verified": False,
            "no_fill_lifecycle_verified": True,
            "final_state_reconciliation_verified": True,
        },
        "cancel_all_verified": True,
        "cancel_all": {
            "request_verified": True,
            "zero_open_orders_verified": True,
        },
        "dead_man_heartbeat": {
            "endpoint": "/v1/heartbeats",
            "endpoint_verified": True,
            "initial_empty_id_verified": True,
            "rotating_id_chain_verified": True,
            "acknowledgment_verified": True,
            "cadence_seconds": 5,
            "stale_placement_disarm_verified": True,
            "automatic_cancel_verified": True,
        },
        "latency_stopgap": {
            "order_reject_handling_verified": True,
            "book_refresh_before_retry_verified": True,
            "cancel_exemption_verified": True,
        },
        "isolated_pilot_wallet": True,
        "pilot_wallet_max_funding_usdc": 25.0,
        "backend_only_signing": True,
        "private_key_storage": "backend_secret_manager",
        "secrets_not_committed": True,
        "secret_redaction": {
            "status_output_verified": True,
            "source_doc_scan_verified": True,
            "generated_artifact_scan_verified": True,
            "no_unredacted_secret_findings": True,
            "scan_scope": [
                "snapshot_tracker_status",
                "src/weather",
                "docs/research",
                "data/snapshots",
                "data/backtest",
            ],
        },
        "source_urls": [
            "https://docs.polymarket.com/api-reference/authentication",
            "https://docs.polymarket.com/trading/fees",
            "https://docs.polymarket.com/concepts/pusd",
        ],
    }
    if not ok:
        payload["eligibility_verified"] = False
        payload["fees_verified"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestMarketMakingRun(unittest.TestCase):
    def test_live_pilot_rejects_multi_market_and_budget_above_operator_cap(self):
        with self.assertRaisesRegex(ValueError, "no more than 100.00 USDC"):
            build_run_once(
                TARGET_DATE,
                100.01,
                mode="live-pilot",
                markets=["atlanta"],
                now=NOW,
            )

        with self.assertRaisesRegex(ValueError, "budget must be finite"):
            build_run_once(
                TARGET_DATE,
                float("nan"),
                mode="live-pilot",
                markets=["atlanta"],
                now=NOW,
            )

        with self.assertRaisesRegex(ValueError, "exactly one market"):
            build_run_once(
                TARGET_DATE,
                25.0,
                mode="live-pilot",
                markets=["atlanta", "austin"],
                now=NOW,
            )

    def test_live_pilot_rejects_nonfinite_or_negative_policy_limits(self):
        with self.assertRaisesRegex(ValueError, "max_event_notional must be finite"):
            build_run_once(
                TARGET_DATE,
                25.0,
                mode="live-pilot",
                markets=["atlanta"],
                now=NOW,
                policy_config={"max_event_notional": float("nan")},
            )

        with self.assertRaisesRegex(ValueError, "quote_ttl_seconds must be finite"):
            build_run_once(
                TARGET_DATE,
                25.0,
                mode="live-pilot",
                markets=["atlanta"],
                now=NOW,
                policy_config={"quote_ttl_seconds": -1},
            )

    def test_run_loop_finalizes_last_tick_exactly_once(self):
        now = datetime(2026, 6, 14, 16, 0, tzinfo=timezone.utc)
        tick_payload = {
            "run_id": "loop-run",
            "run_folder": "loop-folder",
        }
        finalized_payload = {
            **tick_payload,
            "scoring_projection": {"status": "PASS"},
        }
        with patch.object(
            market_making_run,
            "build_run_once",
            return_value=tick_payload,
        ) as build_once, patch.object(
            market_making_run,
            "utc_now",
            return_value=now,
        ), patch.object(
            market_making_run.time,
            "sleep",
        ) as sleep, patch.object(
            market_making_run,
            "keep_system_awake",
        ), patch.object(
            market_making_run,
            "finalize_scoring_projection",
            return_value=finalized_payload,
        ) as finalize:
            result = market_making_run.run_loop(
                TARGET_DATE,
                500,
                "paper-live-forward",
                markets=["atlanta"],
                until_utc="2026-06-14T17:00:00+00:00",
                max_ticks=1,
            )

        build_once.assert_called_once()
        sleep.assert_not_called()
        finalize.assert_called_once_with(tick_payload)
        self.assertIs(result, finalized_payload)

    def test_main_finalizes_one_shot_once_and_does_not_refinalize_loop_result(self):
        one_shot_payload = {"run_folder": "one-shot"}
        finalized_payload = {
            **one_shot_payload,
            "scoring_projection": {"status": "PASS"},
        }
        with patch.object(
            market_making_run,
            "build_run_once",
            return_value=one_shot_payload,
        ) as build_once, patch.object(
            market_making_run,
            "finalize_scoring_projection",
            return_value=finalized_payload,
        ) as finalize, patch.object(
            market_making_run,
            "format_run_cli_summary",
            return_value="one-shot",
        ):
            result = market_making_run.main([
                "--date",
                TARGET_DATE,
                "--mode",
                "shadow",
                "--budget-usdc",
                "500",
            ])

        build_once.assert_called_once()
        finalize.assert_called_once_with(one_shot_payload)
        self.assertIs(result, finalized_payload)

        loop_payload = {
            "run_folder": "loop",
            "scoring_projection": {"status": "PASS"},
        }
        with patch.object(
            market_making_run,
            "run_loop",
            return_value=loop_payload,
        ) as run_loop, patch.object(
            market_making_run,
            "finalize_scoring_projection",
        ) as finalize, patch.object(
            market_making_run,
            "format_run_cli_summary",
            return_value="loop",
        ):
            result = market_making_run.main([
                "--date",
                TARGET_DATE,
                "--mode",
                "paper-live-forward",
                "--max-ticks",
                "1",
                "--budget-usdc",
                "500",
            ])

        run_loop.assert_called_once()
        finalize.assert_not_called()
        self.assertIs(result, loop_payload)

    def test_runtime_identity_snapshot_uses_recorded_scope_for_loop_status(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_dir = root / "src" / "weather"
            source_dir.mkdir(parents=True)
            scoped_file = source_dir / "loaded.py"
            unrelated_file = source_dir / "unrelated.py"
            scoped_file.write_text("VALUE = 1\n", encoding="utf-8")
            unrelated_file.write_text("VALUE = 'before'\n", encoding="utf-8")

            recorded = get_runtime_identity(root, scope_files=["src/weather/loaded.py"])
            unrelated_file.write_text("VALUE = 'after'\n", encoding="utf-8")

            snapshots_root = root / "data" / "snapshots"
            snapshots_root.mkdir(parents=True)
            observation_status = root / "data" / "observation_trigger_status.json"
            observation_status.parent.mkdir(parents=True, exist_ok=True)
            status_payload = {"pid": 123, "runtime_identity": recorded}
            for path in (
                snapshots_root / "loop_status.json",
                snapshots_root / "clob_loop_status.json",
                observation_status,
            ):
                path.write_text(json.dumps(status_payload), encoding="utf-8")

            payload = runtime_identity_snapshot(observation_status, snapshots_root)
            self.assertEqual(payload["drift_count"], 0)
            self.assertTrue(all(row["runtime_identity_matches_current"] for row in payload["loops"]))

            scoped_file.write_text("VALUE = 2\n", encoding="utf-8")

            stale_payload = runtime_identity_snapshot(observation_status, snapshots_root)
            self.assertEqual(stale_payload["drift_count"], 3)
            self.assertTrue(all(row["runtime_identity_matches_current"] is False for row in stale_payload["loops"]))

    def test_useful_work_liveness_blocks_all_market_active_day_stale_work(self):
        now = datetime(2026, 6, 14, 16, 0, tzinfo=timezone.utc)
        preflight_rows = [{
            "market_id": "atlanta",
            "latest_capture_utc": "2026-06-14T15:00:00+00:00",
            "model_age_seconds": 3600.0,
            "book_audit": {
                "last_capture_utc": "2026-06-14T15:00:00+00:00",
                "trailing_age_seconds": 3600.0,
            },
            "gates": [
                {"name": "snapshot_model_rows", "ok": True, "severity": "missing", "detail": "ok"},
                {"name": "model_freshness", "ok": False, "severity": "stale", "detail": "stale model"},
                {"name": "clob_books", "ok": True, "severity": "missing", "detail": "ok"},
                {"name": "clob_features", "ok": True, "severity": "missing", "detail": "ok"},
                {"name": "clob_freshness", "ok": False, "severity": "stale", "detail": "stale CLOB"},
            ],
            "csv_encoding": {"issue_count": 1, "quarantined_row_count": 2},
        }]
        payload = build_useful_work_liveness(
            preflight_rows,
            runtime_identity={
                "loops": [{
                    "name": "weather_snapshots",
                    "status_path": "snapshot-loop.json",
                    "runtime_identity_matches_current": False,
                }]
            },
            observation_status_path=Path("observation_status.json"),
            snapshots_root=Path("snapshots"),
            runs_root=Path("mm_runs"),
            policy_config={"max_model_age_seconds": 120.0, "max_book_age_seconds": 120.0},
            now=now,
            all_market_scope=True,
            evidence_mode=EVIDENCE_MODE_ACTIVE_DAY,
            mode="paper-live-forward",
            snapshot_loop_status={
                "iterations": 1,
                "last_market_results": {"atlanta": {"written": False}},
            },
            clob_loop_status={
                "iterations": 0,
                "started_at": "2026-06-14T15:00:00+00:00",
            },
            observation_status_raw={
                "last_heartbeat": "2026-06-14T15:59:50+00:00",
                "last_poll_at_utc": "2026-06-14T15:59:50+00:00",
                "last_poll_results": {
                    "atlanta": {
                        "snapshot": {
                            "status": "stale_code",
                            "blocked": True,
                        }
                    }
                },
            },
            daily_roll_status={
                "status": "disk_full",
                "disk_capacity_preflight": {
                    "ok": False,
                    "status": "LOW_SPACE",
                    "remediation_command": "free disk",
                },
            },
        )

        self.assertEqual(payload["status"], "BLOCK")
        self.assertFalse(payload["ok"])
        roots = payload["root_cause_counts"]
        self.assertIn("stale_runtime_identity", roots)
        self.assertIn("snapshot_loop_no_useful_write", roots)
        self.assertIn("clob_loop_zero_iterations", roots)
        self.assertIn("observation_trigger_stale_code_markets", roots)
        self.assertIn("stale_or_missing_snapshot_model_rows", roots)
        self.assertIn("stale_or_missing_clob_book_rows", roots)
        self.assertIn("clob_csv_encoding_issue", roots)
        self.assertIn("disk_full_or_low_space", roots)

        remediation = build_preflight_remediation(
            {
                "run_id": "run-1",
                "target_date": TARGET_DATE,
                "mode": "paper-live-forward",
                "status": "PASS",
                "markets": [],
                "useful_work_liveness": payload,
            },
            now,
        )
        self.assertEqual(remediation["status"], "BLOCK")
        self.assertFalse(remediation["counts_toward_live_forward_gate"])
        self.assertIn("stale_runtime_identity", remediation["root_cause_counts"])

    def test_live_forward_gate_blocks_when_run_level_liveness_fails(self):
        gates = [
            "active_event",
            "snapshot_model_rows",
            "model_freshness",
            "source_status_rows",
            "source_status_fresh",
            "clob_discovery",
            "clob_tokens",
            "clob_books",
            "clob_features",
            "clob_freshness",
            "observation_trigger",
            "promotion_state",
            "reward_metadata",
        ]
        preflight = {
            "run_id": "run-1",
            "target_date": TARGET_DATE,
            "mode": "paper-live-forward",
            "generated_at_utc": NOW,
            "observation_status": {"fresh": True, "last_heartbeat": "2026-06-14T15:59:50+00:00"},
            "useful_work_liveness": {
                "status": "BLOCK",
                "ok": False,
                "enforced": True,
                "blocker_count": 1,
                "blockers": [{
                    "gate": "snapshot_loop_activity",
                    "root_cause": "snapshot_loop_no_useful_write",
                }],
            },
            "markets": [{
                "market_id": "atlanta",
                "city": "Atlanta",
                "target_date": TARGET_DATE,
                "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                "status": "PASS",
                "latest_capture_utc": "2026-06-14T15:59:50+00:00",
                "model_age_seconds": 10.0,
                "book_audit": {
                    "last_capture_utc": "2026-06-14T15:59:50+00:00",
                    "trailing_age_seconds": 10.0,
                },
                "gates": [
                    {"name": name, "ok": True, "severity": "missing", "detail": "ok"}
                    for name in gates
                ],
            }],
        }

        gate = build_live_forward_gate(
            preflight,
            policy_config={"max_model_age_seconds": 120.0, "max_book_age_seconds": 120.0},
            now=NOW,
        )

        self.assertEqual(gate["status"], "BLOCK")
        self.assertFalse(gate["counts_toward_live_forward_gate"])
        self.assertTrue(gate["evidence"]["paper_trading_evidence"]["all_selected_markets_count"])
        self.assertEqual(gate["summary"]["run_level_failure_counts"]["useful_work_liveness"], 1)

    def test_model_variant_bakeoff_loads_configured_external_variant_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            variants = root / "variants.csv"
            variants.write_text(
                "variant_id,variant_family,market_id,target_date,snapshot_id,band_key,probability,"
                "artifact_hash,postprocess_config_hash,feature_schema_version\n"
                "external_dynamic,dynamic_source_freshness,atlanta,2026-06-14,s1,eq:80.0-81.0,0.62,"
                "hash1,post1,schema1\n",
                encoding="utf-8",
            )
            inputs = [{
                "market_id": "atlanta",
                "target_date": "2026-06-14",
                "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                "snapshot_id": "s1",
                "captured_at_utc": "2026-06-14T15:59:50+00:00",
                "model_version": "candidate",
                "range_label": "80-81 F",
                "bin_kind": "eq",
                "bin_value": "80",
                "bin_value_hi": "81",
                "fair_probability": "0.50",
                "model_probability": "0.50",
                "market_yes": "0.50",
                "clob_midpoint": "0.50",
                "clob_spread": "0.02",
                "clob_book_age_seconds": "10",
                "book_depth_1pct_total": "100",
                "model_age_seconds": "10",
                "watcher_age_seconds": "10",
                "heartbeat_ok": True,
                "source_fresh": True,
                "market_status": "active",
                "promotion_state": "PASS",
            }]

            rows, payload = build_model_variant_quote_rows(
                inputs,
                {
                    "maker_model_variant_paths": str(variants),
                    "maker_model_variant_basket_id": "test_basket",
                    "max_book_age_seconds": 120.0,
                    "max_model_age_seconds": 120.0,
                    "max_watcher_age_seconds": 120.0,
                    "min_depth_1pct_total": 1.0,
                    "tick_size": 0.001,
                    "min_price": 0.001,
                    "max_price": 0.999,
                    "quote_size": 5.0,
                    "harvest_half_spread": 0.01,
                    "max_harvest_spread": 0.08,
                    "max_edge_spread": 0.12,
                    "shadow_disagreement_stand_down": 0.08,
                    "edge_min_advantage": 0.03,
                    "edge_fee_buffer": 0.005,
                    "adverse_selection_buffer": 0.01,
                    "max_event_notional": 25.0,
                    "max_band_notional": 10.0,
                    "max_daily_loss": 25.0,
                    "information_event_calendar_enabled": False,
                    "event_gate_exception_enabled": False,
                    "event_gate_exception_event_classes": "",
                    "event_gate_exception_evidence_status": "",
                    "event_gate_exception_evidence_id": "",
                    "event_gate_exception_risk_cap_usdc": 0.0,
                    "early_hour_guardrail_enabled": False,
                    "early_hour_guardrail_market_weight": 0.35,
                    "early_hour_guardrail_size_multiplier": 1.0,
                    "early_hour_guardrail_quote_widen_buffer": 0.0,
                    "early_hour_guardrail_min_edge_multiplier": 1.0,
                    "snapshot_cadence_quality_enabled": False,
                    "snapshot_cadence_degraded_permission": "allow",
                    "snapshot_cadence_confidence_haircut": 1.0,
                    "snapshot_cadence_quote_size_multiplier": 1.0,
                    "snapshot_cadence_quote_widen_buffer": 0.0,
                    "max_snapshot_cadence_gap_seconds": 900.0,
                    "snapshot_cadence_stale_model_seconds": 900.0,
                    "current_high_trust_gate_enabled": False,
                },
                target_date="2026-06-14",
                runtime_identity={"current_identity": {"git_commit": "abc"}},
                now=NOW,
            )

        variant_ids = {row["model_variant_id"] for row in rows}
        self.assertIn("served_current", variant_ids)
        self.assertIn("external_dynamic", variant_ids)
        external = next(row for row in rows if row["model_variant_id"] == "external_dynamic")
        self.assertEqual(external["model_variant_artifact_hash"], "hash1")
        self.assertEqual(external["model_variant_feature_schema"], "schema1")
        self.assertIn("external_dynamic", payload["emitted_variant_ids"])
        self.assertEqual(payload["basket_id"], "test_basket")

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

    def test_data_layer_live_gate_accepts_summary_or_gzip_raw_book_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for artifact_key in ("order_books_summary", "order_books_long_gzip"):
                with self.subTest(artifact_key=artifact_key):
                    path = write_data_layer_audit(
                        root / f"{artifact_key}.json",
                        ok=True,
                        raw_book_artifact=artifact_key,
                    )

                    gate = load_data_layer_live_gate(path, TARGET_DATE, "live-pilot")

                    self.assertTrue(gate["ok"])
                    self.assertTrue(gate["checks"]["target_date_raw_book_artifact"])
                    self.assertEqual(gate["target_date_raw_book_artifact_days"], 1)

    def test_data_layer_live_gate_rejects_derived_clob_without_raw_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_data_layer_audit(
                root / "derived_only.json",
                ok=True,
                raw_clob_artifacts=False,
            )

            gate = load_data_layer_live_gate(path, TARGET_DATE, "live-pilot")

        self.assertFalse(gate["ok"])
        self.assertIn("target_date_clob_token_artifact", gate["missing"])
        self.assertIn("target_date_raw_book_artifact", gate["missing"])
        self.assertEqual(gate["target_date_clob_feature_days"], 1)
        self.assertEqual(gate["target_date_book_available_days"], 1)

    def test_platform_verification_gate_requires_current_verified_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = write_platform_verification(root / "platform_good.json")
            bad = write_platform_verification(root / "platform_bad.json", ok=False)
            stale = write_platform_verification(
                root / "platform_stale.json",
                verified_at="2026-06-13T15:59:00+00:00",
            )
            wrong_date = write_platform_verification(root / "platform_wrong_date.json", target_date="2026-06-15")
            no_fill = write_platform_verification(root / "platform_no_fill.json")
            no_fill_payload = json.loads(no_fill.read_text(encoding="utf-8"))
            no_fill_payload["private_user_stream"]["fill_event_verified"] = False
            no_fill_payload["private_user_stream"]["no_fill_lifecycle_verified"] = True
            no_fill.write_text(json.dumps(no_fill_payload), encoding="utf-8")

            good_gate = load_platform_verification_gate(good, TARGET_DATE, "live-pilot", now=NOW)
            bad_gate = load_platform_verification_gate(bad, TARGET_DATE, "live-pilot", now=NOW)
            stale_gate = load_platform_verification_gate(stale, TARGET_DATE, "live-pilot", now=NOW)
            wrong_date_gate = load_platform_verification_gate(wrong_date, TARGET_DATE, "live-pilot", now=NOW)
            no_fill_gate = load_platform_verification_gate(no_fill, TARGET_DATE, "live-pilot", now=NOW)

        self.assertTrue(good_gate["ok"])
        self.assertFalse(bad_gate["ok"])
        self.assertIn("eligibility_verified", bad_gate["missing"])
        self.assertIn("fees_verified", bad_gate["missing"])
        self.assertFalse(stale_gate["ok"])
        self.assertIn("verified_at_recent", stale_gate["missing"])
        self.assertFalse(wrong_date_gate["ok"])
        self.assertIn("target_date_matches", wrong_date_gate["missing"])
        self.assertTrue(no_fill_gate["ok"], no_fill_gate["missing"])
        self.assertFalse(load_platform_verification_gate(good, TARGET_DATE, "shadow", now=NOW)["required"])

    def test_platform_verification_gate_binds_stage1_bundle_content_and_derivations(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_platform_verification(Path(tmp) / "platform_stage1.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["stage1_lifecycle_bundle"]["lifecycle_results"]["dead_man"][
                "order_id"
            ] = "cancel-order"
            payload["stage1_lifecycle_bundle"]["bundle_sha256"] = (
                stage1_lifecycle_bundle_sha256(payload["stage1_lifecycle_bundle"])
            )
            payload["stage1_lifecycle_bundle_sha256"] = payload[
                "stage1_lifecycle_bundle"
            ]["bundle_sha256"]
            payload["private_user_stream"]["fill_event_verified"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")

            gate = load_platform_verification_gate(
                path,
                TARGET_DATE,
                "live-pilot",
                now=NOW,
                requested_budget_usdc=25,
            )

        self.assertFalse(gate["ok"])
        self.assertIn("stage1_probe_orders_are_distinct", gate["missing"])
        self.assertIn(
            "stage1_derived_evidence_matches_platform_fields",
            gate["missing"],
        )

    def test_platform_verification_gate_rejects_non_pusd_settlement_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_platform_verification(Path(tmp) / "platform_unit.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["settlement_unit"] = "USDC.e"
            path.write_text(json.dumps(payload), encoding="utf-8")

            gate = load_platform_verification_gate(
                path,
                TARGET_DATE,
                "live-pilot",
                now=NOW,
            )

        self.assertFalse(gate["ok"])
        self.assertIn("settlement_unit_is_native_pusd", gate["missing"])
        self.assertIn(
            "stage1_lifecycle_bundle_settlement_unit_matches",
            gate["missing"],
        )

    def test_platform_verification_gate_rejects_legacy_api_lifecycle_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_platform_verification(root / "platform_legacy.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["schema_version"] = "mm_platform_verification_v0.1"
            payload.pop("maker_only_order_field", None)
            payload.pop("maker_only_order_field_verified", None)
            payload.pop("private_user_stream", None)
            payload.pop("cancel_all", None)
            payload.pop("latency_stopgap", None)
            path.write_text(json.dumps(payload), encoding="utf-8")

            gate = load_platform_verification_gate(path, TARGET_DATE, "live-pilot", now=NOW)

        self.assertFalse(gate["ok"])
        self.assertIn("schema_version_supported", gate["missing"])
        self.assertIn("maker_only_order_field_supported", gate["missing"])
        self.assertIn("private_user_stream_final_state_reconciliation_verified", gate["missing"])
        self.assertIn("cancel_all_zero_open_orders_verified", gate["missing"])

    def test_platform_verification_gate_requires_structured_live_api_proofs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_platform_verification(root / "platform_unproven_api.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["maker_only_order_field_verified"] = False
            payload["private_user_stream"]["fill_event_verified"] = False
            payload["private_user_stream"]["no_fill_lifecycle_verified"] = False
            payload["private_user_stream"]["final_state_reconciliation_verified"] = False
            payload["cancel_all"]["zero_open_orders_verified"] = False
            payload["latency_stopgap"]["book_refresh_before_retry_verified"] = False
            payload["latency_stopgap"]["cancel_exemption_verified"] = False
            path.write_text(json.dumps(payload), encoding="utf-8")

            gate = load_platform_verification_gate(path, TARGET_DATE, "live-pilot", now=NOW)

        self.assertFalse(gate["ok"])
        self.assertIn("maker_only_order_field_verified", gate["missing"])
        self.assertIn(
            "private_user_stream_fill_or_no_fill_lifecycle_verified",
            gate["missing"],
        )
        self.assertIn("private_user_stream_final_state_reconciliation_verified", gate["missing"])
        self.assertIn("cancel_all_zero_open_orders_verified", gate["missing"])

    def test_platform_verification_gate_rejects_polymarket_us(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_platform_verification(
                Path(tmp) / "platform_us.json",
                platform="polymarket_us",
            )
            gate = load_platform_verification_gate(path, TARGET_DATE, "live-pilot", now=NOW)

        self.assertFalse(gate["ok"])
        self.assertIn("platform_supported", gate["missing"])
        self.assertIn("international_jurisdiction_verified", gate["missing"])

    def test_platform_verification_gate_requires_consistent_wallet_and_heartbeat_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_platform_verification(Path(tmp) / "platform_identity.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["signature_type_id"] = 0
            payload["wallet_identity"]["api_key_owner_address"] = "not-an-address"
            payload["wallet_identity"]["consistency_verified"] = False
            payload["dead_man_heartbeat"]["rotating_id_chain_verified"] = False
            payload["dead_man_heartbeat"]["cadence_seconds"] = 5.01
            path.write_text(json.dumps(payload), encoding="utf-8")

            gate = load_platform_verification_gate(
                path,
                TARGET_DATE,
                "live-pilot",
                now=NOW,
            )

        self.assertFalse(gate["ok"])
        self.assertIn("signature_type_consistent", gate["missing"])
        self.assertIn("api_key_owner_address_valid", gate["missing"])
        self.assertIn("wallet_identity_consistency_verified", gate["missing"])
        self.assertIn("dead_man_heartbeat_rotating_id_chain_verified", gate["missing"])
        self.assertIn("dead_man_heartbeat_cadence_verified", gate["missing"])

    def test_platform_verification_gate_accepts_existing_gnosis_safe_topology(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_platform_verification(Path(tmp) / "platform_safe.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["wallet_type"] = "gnosis_safe"
            payload["signature_type"] = "POLY_GNOSIS_SAFE"
            payload["signature_type_id"] = 2
            payload["wallet_identity"]["order_signer_address"] = (
                payload["wallet_identity"]["private_key_signer_address"]
            )
            path.write_text(json.dumps(payload), encoding="utf-8")

            gate = load_platform_verification_gate(
                path,
                TARGET_DATE,
                "live-pilot",
                now=NOW,
            )

        self.assertTrue(gate["ok"], gate["missing"])

    def test_platform_verification_gate_enforces_operator_and_wallet_budget_caps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_platform_verification(root / "platform.json")
            within_cap = load_platform_verification_gate(
                path,
                TARGET_DATE,
                "live-pilot",
                now=NOW,
                requested_budget_usdc=25.0,
            )
            over_wallet_cap = load_platform_verification_gate(
                path,
                TARGET_DATE,
                "live-pilot",
                now=NOW,
                requested_budget_usdc=25.01,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["pilot_wallet_max_funding_usdc"] = 100.01
            path.write_text(json.dumps(payload), encoding="utf-8")
            over_operator_cap = load_platform_verification_gate(
                path,
                TARGET_DATE,
                "live-pilot",
                now=NOW,
                requested_budget_usdc=25.0,
            )

        self.assertTrue(within_cap["ok"])
        self.assertFalse(over_wallet_cap["ok"])
        self.assertIn("requested_budget_within_pilot_wallet_cap", over_wallet_cap["missing"])
        self.assertFalse(over_operator_cap["ok"])
        self.assertIn("pilot_wallet_cap_within_operator_limit", over_operator_cap["missing"])

    def test_platform_verification_gate_rejects_unbacked_or_overfunded_wallet(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_platform_verification(Path(tmp) / "platform.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["collateral_balance_usdc"] = 25.01
            payload["collateral_allowance_usdc"] = 0.0
            path.write_text(json.dumps(payload), encoding="utf-8")

            gate = load_platform_verification_gate(
                path,
                TARGET_DATE,
                "live-pilot",
                now=NOW,
                requested_budget_usdc=25.0,
            )

        self.assertFalse(gate["ok"])
        self.assertIn("collateral_balance_within_wallet_cap", gate["missing"])
        self.assertIn("collateral_allowance_backs_budget", gate["missing"])

    def test_platform_verification_gate_rejects_secret_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_platform_verification(root / "platform_secret.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["private_key"] = "do-not-store"
            path.write_text(json.dumps(payload), encoding="utf-8")

            gate = load_platform_verification_gate(path, TARGET_DATE, "live-pilot", now=NOW)

        self.assertFalse(gate["ok"])
        self.assertIn("no_secret_material", gate["missing"])

    def test_platform_verification_gate_requires_secret_redaction_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_platform_verification(root / "platform_redaction_missing.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["secret_redaction"]["generated_artifact_scan_verified"] = False
            payload["secret_redaction"]["scan_scope"] = []
            path.write_text(json.dumps(payload), encoding="utf-8")

            gate = load_platform_verification_gate(path, TARGET_DATE, "live-pilot", now=NOW)

        self.assertFalse(gate["ok"])
        self.assertIn("secret_redaction_generated_artifact_scan_verified", gate["missing"])
        self.assertIn("secret_redaction_scan_scope_recorded", gate["missing"])

    def test_platform_verification_gate_rejects_unredacted_secret_query_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_platform_verification(root / "platform_secret_query.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["redaction_evidence_url"] = "https://example.invalid/status?apiKey=synthetic-secret"
            path.write_text(json.dumps(payload), encoding="utf-8")

            gate = load_platform_verification_gate(path, TARGET_DATE, "live-pilot", now=NOW)

        self.assertFalse(gate["ok"])
        self.assertIn("no_secret_material", gate["missing"])

    def test_live_pilot_blocks_when_latest_data_layer_audit_lacks_clob_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
            status = root / "observation_status.json"
            write_observation_status(status)
            known_edge = write_known_edge_map(root / "known_edge.json")
            live_readiness = write_live_readiness(root / "live_readiness.json")
            bad_audit = write_data_layer_audit(root / "bad_data_layer_audit.json", ok=False)
            platform_verification = write_platform_verification(root / "platform_verification.json")

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
                platform_verification_path=platform_verification,
            )

            preflight = json.loads(Path(payload["preflight_path"]).read_text(encoding="utf-8"))
            gates = {
                gate["name"]: gate
                for gate in preflight["markets"][0]["gates"]
            }

        self.assertEqual(payload["preflight_status"], "BLOCK")
        self.assertEqual(payload["quote_outcome"]["status"], "preflight_blocked")
        self.assertEqual(payload["quote_permission_rows"], 0)
        self.assertFalse(preflight["data_layer_live_gate"]["ok"])
        self.assertFalse(gates["data_layer_live_gate"]["ok"])
        self.assertIn("data-layer audit missing live CLOB proof", gates["data_layer_live_gate"]["detail"])

    def test_preflight_blocks_source_status_degradation_even_when_a_source_is_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
            folder = snapshots_root / "highest-temperature-in-atlanta-on-june-14-2026"
            write_csv(
                folder / "source_status_long.csv",
                [
                    "snapshot_id",
                    "captured_at_utc",
                    "captured_at_local",
                    "event_slug",
                    "model_version",
                    "source",
                    "source_family",
                    "ok",
                    "status",
                    "stale",
                    "http_status",
                    "degradation_state",
                    "cache_status",
                    "fetched_at",
                    "age_minutes",
                    "ttl_minutes",
                    "latency_ms",
                    "payload_hash",
                    "row_count",
                    "source_url",
                    "error",
                ],
                [
                    {
                        "snapshot_id": "s1",
                        "captured_at_utc": NOW,
                        "captured_at_local": NOW,
                        "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                        "model_version": "candidate",
                        "source": "weather_forecast",
                        "source_family": "weather_forecast",
                        "ok": "true",
                        "status": "fresh",
                        "stale": "false",
                        "http_status": "200",
                        "degradation_state": "healthy",
                        "cache_status": "fresh",
                        "fetched_at": NOW,
                        "age_minutes": "0.5",
                        "ttl_minutes": "90",
                        "latency_ms": "10",
                        "payload_hash": "abc",
                        "row_count": "1",
                        "source_url": "",
                        "error": "",
                    },
                    {
                        "snapshot_id": "s1",
                        "captured_at_utc": NOW,
                        "captured_at_local": NOW,
                        "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                        "model_version": "candidate",
                        "source": "wu_history",
                        "source_family": "wu_history",
                        "ok": "false",
                        "status": "settlement_source_auth_failure",
                        "stale": "false",
                        "http_status": "403",
                        "degradation_state": "settlement_source_auth_failure",
                        "cache_status": "auth_failure",
                        "fetched_at": NOW,
                        "age_minutes": "0.5",
                        "ttl_minutes": "90",
                        "latency_ms": "10",
                        "payload_hash": "def",
                        "row_count": "0",
                        "source_url": "https://example.invalid/v1/history?apiKey=&units=e",
                        "error": "403 Client Error for url: https://example.invalid/v1/history?apiKey=&units=e",
                    },
                ],
            )
            status = root / "observation_status.json"
            write_observation_status(status)
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
                run_id="source-degradation-blocked",
                now=NOW,
            )

            preflight = json.loads(Path(payload["preflight_path"]).read_text(encoding="utf-8"))
            gates = {
                gate["name"]: gate
                for gate in preflight["markets"][0]["gates"]
            }
            remediation = json.loads(Path(payload["preflight_remediation_path"]).read_text(encoding="utf-8"))

        self.assertEqual(payload["preflight_status"], "BLOCK")
        self.assertEqual(payload["quote_permission_rows"], 0)
        self.assertEqual(payload["live_trade_permission_rows"], 0)
        self.assertTrue(gates["source_status_fresh"]["ok"])
        self.assertFalse(gates["source_status_degradation"]["ok"])
        self.assertIn("settlement_auth_failures=1", gates["source_status_degradation"]["detail"])
        self.assertEqual(
            preflight["markets"][0]["source_status_degradation"]["root_cause"],
            "source_status_degradation_blocked",
        )
        self.assertIn("source_status_degradation_blocked", remediation["root_cause_counts"])
        source_incidents = [
            row for row in remediation["incidents"]
            if row.get("gate") == "source_status_degradation"
        ]
        self.assertTrue(source_incidents)
        self.assertEqual(
            source_incidents[0]["suggested_command"],
            "python -m weather.collection.snapshot_tracker --backfill-source-status --overwrite-source-status",
        )
        self.assertTrue(source_incidents[0]["optional_provider_auth_failure"])
        self.assertIn("free-source replacement", source_incidents[0]["external_prerequisite"])
        self.assertFalse(any("credential" in key for key in source_incidents[0]))
        self.assertIn(source_incidents[0]["suggested_command"], source_incidents[0]["repair_sequence"])

    def test_preflight_allows_paid_weather_auth_failure_with_free_source_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "highest-temperature-in-atlanta-on-june-14-2026"
            fieldnames = [
                "snapshot_id",
                "captured_at_utc",
                "captured_at_local",
                "event_slug",
                "model_version",
                "source",
                "source_family",
                "ok",
                "status",
                "stale",
                "http_status",
                "degradation_state",
                "cache_status",
                "fetched_at",
                "age_minutes",
                "ttl_minutes",
                "latency_ms",
                "payload_hash",
                "row_count",
                "source_url",
                "error",
            ]

            def row(source, *, ok=True, status="fresh", http_status="200", degradation_state="healthy"):
                return {
                    "snapshot_id": "s2",
                    "captured_at_utc": NOW,
                    "captured_at_local": NOW,
                    "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                    "model_version": "candidate",
                    "source": source,
                    "source_family": source,
                    "ok": str(ok).lower(),
                    "status": status,
                    "stale": "false",
                    "http_status": http_status,
                    "degradation_state": degradation_state,
                    "cache_status": "fresh" if ok else "auth_failure",
                    "fetched_at": NOW,
                    "age_minutes": "0.5",
                    "ttl_minutes": "90",
                    "latency_ms": "10",
                    "payload_hash": source,
                    "row_count": "1" if ok else "0",
                    "source_url": "",
                    "error": "",
                }

            write_csv(
                folder / "source_status_long.csv",
                fieldnames,
                [
                    row("local_history"),
                    row("metar"),
                    row("nws_hourly"),
                    row(
                        "weather_forecast",
                        ok=False,
                        status="failed",
                        http_status="401",
                        degradation_state="failed",
                    ),
                    row(
                        "wu_current",
                        ok=False,
                        status="failed",
                        http_status="401",
                        degradation_state="failed",
                    ),
                    row(
                        "wu_history",
                        ok=False,
                        status="settlement_source_auth_failure",
                        http_status="401",
                        degradation_state="settlement_source_auth_failure",
                    ),
                ],
            )

            gate = source_status_degradation_preflight(folder, "s2")

        self.assertEqual(gate["status"], "PASS")
        self.assertTrue(gate["ok"])
        self.assertTrue(gate["trading_evidence_allowed"])
        self.assertTrue(gate["live_trade_permission_allowed"])
        self.assertTrue(gate["promotion_readiness_allowed"])
        self.assertTrue(gate["free_source_replacement_allowed"])
        self.assertFalse(any("weather_com" in key for key in gate))
        self.assertEqual(gate["blocking_family_count"], 0)
        self.assertEqual(gate["settlement_auth_failure_source_count"], 3)

    def test_live_pilot_blocks_without_platform_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
            status = root / "observation_status.json"
            write_observation_status(status)
            known_edge = write_known_edge_map(root / "known_edge.json")
            live_readiness = write_live_readiness(root / "live_readiness.json")
            data_layer_audit = write_data_layer_audit(root / "data_layer_audit.json", ok=True)

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
                run_id="live-platform-blocked",
                now=NOW,
                pilot=True,
                confirm_live_orders=True,
                live_readiness_path=live_readiness,
                data_layer_audit_path=data_layer_audit,
                platform_verification_path=root / "missing_platform_verification.json",
            )

            preflight = json.loads(Path(payload["preflight_path"]).read_text(encoding="utf-8"))
            gates = {
                gate["name"]: gate
                for gate in preflight["markets"][0]["gates"]
            }
            remediation = json.loads(Path(payload["preflight_remediation_path"]).read_text(encoding="utf-8"))

        self.assertEqual(payload["preflight_status"], "BLOCK")
        self.assertEqual(payload["live_trade_permission_rows"], 0)
        self.assertFalse(preflight["platform_verification_gate"]["ok"])
        self.assertFalse(gates["platform_verification_gate"]["ok"])
        self.assertIn("platform-verification artifact missing", gates["platform_verification_gate"]["detail"])
        self.assertIn("platform_verification_gate_blocked", remediation["root_cause_counts"])

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
                "model_variant_quote_intents_long.csv",
                "model_variant_bakeoff.json",
                "model_variant_bakeoff.md",
                "budget_ledger.jsonl",
                "order_lifecycle.jsonl",
                "risk_events.jsonl",
                "fills_long.csv",
                "run_report.md",
            ]:
                self.assertTrue((run_folder / name).exists(), name)
            self.assertEqual(payload["row_count"], 2)
            self.assertEqual(payload["quote_intent_rows"], 2)
            self.assertEqual(payload["quote_rows"], 2)
            self.assertEqual(payload["no_quote_rows"], 1)
            self.assertEqual(payload["quote_outcome"]["quote_intent_rows"], 2)
            self.assertEqual(payload["quote_outcome"]["quote_rows"], 2)
            self.assertEqual(payload["quote_outcome"]["no_quote_rows"], 1)
            self.assertEqual(payload["latest_tick"]["quote_intent_rows"], 2)
            self.assertEqual(payload["latest_tick"]["quote_rows"], 2)
            self.assertEqual(payload["latest_tick"]["no_quote_rows"], 1)
            self.assertEqual(payload["live_trade_permission_rows"], 0)
            self.assertEqual(payload["reason_counts"]["QUOTE_HARVEST_MID"], 1)
            self.assertEqual(payload["reason_counts"]["NO_QUOTE_BUDGET_EXHAUSTED"], 1)
            self.assertEqual(payload["known_edge_map"]["path"], str(known_edge))
            self.assertTrue(payload["known_edge_map"]["exists"])
            self.assertEqual(payload["known_edge_map"]["schema_version"], "mm_known_edge_map_v0.1")
            self.assertEqual(payload["known_edge_map"]["record_count"], 1)
            self.assertFalse(payload["known_edge_map"]["diagnostic_only"])
            self.assertIn("information_event_gate", payload)
            self.assertGreaterEqual(payload["information_event_gate"]["widen_rows"], 1)
            self.assertEqual(payload["tape_integrity"]["status"], "PASS")
            self.assertEqual(payload["tape_integrity"]["actual_rows"], payload["cumulative_row_count"])
            rows = read_csv(run_folder / "quote_intents_long.csv")
            self.assertEqual({row["run_id"] for row in rows}, {"run-1"})
            self.assertEqual({row["model_variant_id"] for row in rows}, {"served_current"})
            self.assertTrue(all(row["served_model_version"] == "candidate" for row in rows))
            self.assertTrue(all(row["event_gate_status"] for row in rows))
            self.assertTrue(all(row["live_trade_permission"] in {"False", "False"} for row in rows))
            variant_rows = read_csv(run_folder / "model_variant_quote_intents_long.csv")
            self.assertEqual(payload["model_variant_row_count"], len(variant_rows))
            self.assertIn("served_current", {row["model_variant_id"] for row in variant_rows})
            self.assertIn("conservative_no_market_baseline", {row["model_variant_id"] for row in variant_rows})
            self.assertIn("model_variant_bakeoff", payload)
            self.assertIn("model_variant_by_policy", payload["model_variant_bakeoff"])
            report = (run_folder / "run_report.md").read_text(encoding="utf-8")
            self.assertIn("## Information Event Gate", report)
            self.assertIn("## Model-Variant Bakeoff", report)
            self.assertIn("Quote tape integrity", report)
            self.assertIn("Latest-tick quote-intent rows: `2`", report)
            self.assertIn("Latest-tick quote-permission rows: `1`", report)
            self.assertIn("Latest-tick no-quote rows: `1`", report)
            self.assertIn("Cumulative quote-intent rows: `2`", report)
            self.assertIn("Cumulative quote-permission rows: `1`", report)
            self.assertIn("Cumulative no-quote rows: `1`", report)
            self.assertNotIn("Latest-tick quote rows:", report)
            self.assertNotIn("Cumulative quote rows:", report)
            budget_events = [
                json.loads(line)
                for line in (run_folder / "budget_ledger.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            max_reserved = max(float(row.get("reserved_usdc") or 0.0) for row in budget_events)
            self.assertLessEqual(max_reserved, 5.0)
            self.assertIn("order_lifecycle", payload)
            self.assertGreaterEqual(payload["order_lifecycle"]["posted_this_tick_count"], 1)

    def test_market_harvest_profile_emits_paper_quotes_without_model_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
            folder = snapshots_root / "highest-temperature-in-atlanta-on-june-14-2026"
            (folder / "snapshots_long.csv").unlink()
            promotion.write_text(json.dumps({
                "decisions": {
                    "markets": [{
                        "market_id": "atlanta",
                        "action": "BLOCK_CANDIDATE",
                        "verdict": "BLOCK",
                    }]
                }
            }), encoding="utf-8")
            status = root / "observation_status.json"
            write_observation_status(status)
            known_edge = write_known_edge_map(
                root / "known_edge.json",
                permission="no_quote",
                reason="model_edge_retired",
            )

            payload = build_run_once(
                TARGET_DATE,
                25.0,
                mode="paper-live-forward",
                permission_profile="market_harvest",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                observation_status_path=status,
                run_id="market-harvest-no-model",
                now=NOW,
                policy_config={
                    "quote_size": 500.0,
                    "max_event_notional": 500.0,
                    "max_band_notional": 500.0,
                    "max_daily_loss": 500.0,
                    "harvest_half_spread": 0.001,
                    "max_harvest_spread": 0.99,
                },
            )

            run_folder = Path(payload["run_folder"])
            preflight = json.loads((run_folder / "preflight.json").read_text(encoding="utf-8"))
            run_config = json.loads((run_folder / "run_config.json").read_text(encoding="utf-8"))
            rows = read_csv(run_folder / "quote_intents_long.csv")

        self.assertEqual(payload["preflight_status"], "PASS")
        self.assertEqual(payload["quote_permission_rows"], 2)
        self.assertEqual(payload["live_trade_permission_rows"], 0)
        self.assertEqual(payload["reason_counts"], {"QUOTE_MARKET_HARVEST_MID": 2})
        self.assertEqual(preflight["permission_profile"], "market_harvest")
        gate_names = {gate["name"] for gate in preflight["markets"][0]["gates"]}
        self.assertNotIn("snapshot_model_rows", gate_names)
        self.assertNotIn("model_freshness", gate_names)
        self.assertIn("market_harvest_paper_only", gate_names)
        self.assertEqual(run_config["permission_profile"], "market_harvest")
        self.assertFalse(run_config["shadow_safety"]["live_trade_permission_allowed"])
        self.assertEqual(run_config["policy_config"]["quote_size"], 5.0)
        self.assertEqual(run_config["policy_config"]["max_event_notional"], 25.0)
        self.assertEqual(run_config["policy_config"]["max_band_notional"], 10.0)
        self.assertEqual(run_config["policy_config"]["max_daily_loss"], 25.0)
        self.assertEqual(run_config["policy_config"]["harvest_half_spread"], 0.01)
        self.assertEqual(run_config["policy_config"]["max_harvest_spread"], 0.08)
        self.assertEqual({row["known_edge_permission"] for row in rows}, {"market_harvest"})
        self.assertEqual({row["promotion_state"] for row in rows}, {"BLOCK"})
        self.assertEqual({row["model_variant_probability_source"] for row in rows}, {"market_mid_no_model"})
        self.assertEqual({row["fair_probability"] for row in rows}, {""})
        self.assertEqual({row["served_fair_probability"] for row in rows}, {""})
        self.assertEqual({row["expected_reward_score"] for row in rows}, {"0.0"})
        self.assertEqual({row["expected_rebate_value"] for row in rows}, {"0.0"})
        self.assertTrue(all(row["live_trade_permission"] == "False" for row in rows))

    def test_market_harvest_profile_rejects_live_pilot_mode(self):
        with self.assertRaisesRegex(ValueError, "paper-only"):
            build_run_once(
                TARGET_DATE,
                25.0,
                mode="live-pilot",
                permission_profile="market_harvest",
                markets=["atlanta"],
                now=NOW,
            )

    def test_blank_clob_tokens_are_market_discovery_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root, blank_tokens=True)
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
                run_id="blank-tokens",
                now=NOW,
            )
            market = payload["markets"][0]
            gates = {gate["name"]: gate for gate in market["gates"]}

        self.assertEqual(payload["preflight_status"], "BLOCK")
        self.assertEqual(payload["root_cause_class"], "blocked_by_market_discovery")
        self.assertEqual(payload["first_failing_gate"], "clob_discovery")
        self.assertFalse(gates["clob_discovery"]["ok"])
        self.assertEqual(market["clob_token_discovery"]["root_cause"], "blank_clob_token_ids")
        self.assertTrue(payload["zero_trades_expected"])

    def test_quote_rows_include_settlement_normalized_current_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
            status = root / "observation_status.json"
            write_observation_status(status, market_ledger={
                "market_id": "atlanta",
                "raw_current_high": 81.7,
                "raw_current_high_bucket": 82,
                "settlement_current_high": 82,
                "high_source": "wu_history",
                "revision_state": "current",
                "settlement_bin_key": "eq:82",
            })
            known_edge = write_known_edge_map(root / "known_edge.json")

            payload = build_run_once(
                TARGET_DATE,
                50.0,
                mode="shadow",
                markets=["atlanta"],
                runs_root=root / "mm_runs",
                snapshots_root=snapshots_root,
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                observation_status_path=status,
                run_id="normalized-high",
                now=NOW,
            )
            rows = read_csv(Path(payload["quote_intents_path"]))
            assessment = payload["markets"][0]["current_high_assessment"]

        self.assertEqual(assessment["settlement_current_high"], 82)
        self.assertEqual(assessment["probability_on_settlement_current_high"], 0.51)
        self.assertTrue(all(row["settlement_current_high"] == "82" for row in rows))
        self.assertTrue(all(row["probability_on_settlement_current_high"] == "0.51" for row in rows))

    def test_run_computes_clob_features_when_feature_file_lags_latest_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
            append_latest_snapshot_without_clob_features(snapshots_root)
            status = root / "observation_status.json"
            write_observation_status(status)
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
                run_id="feature-catchup",
                now=NOW,
            )

            preflight = json.loads(Path(payload["preflight_path"]).read_text(encoding="utf-8"))
            quote_rows = read_csv(Path(payload["quote_intents_path"]))

        self.assertEqual(payload["preflight_status"], "PASS")
        self.assertEqual(preflight["markets"][0]["latest_snapshot_id"], "s2")
        self.assertEqual(preflight["markets"][0]["clob_feature_rows"], 2)
        self.assertNotIn("NO_QUOTE_MISSING_PREFLIGHT", payload["reason_counts"])
        self.assertTrue(all(row["snapshot_id"] == "s2" for row in quote_rows))
        self.assertTrue(any(row.get("book_age_seconds") == "30.0" for row in quote_rows))

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
            clob_incidents = [row for row in incidents if row.get("gate") == "clob_freshness"]
            self.assertTrue(clob_incidents)
            self.assertIn("161", clob_incidents[0]["roadmap_owner_items"])
            self.assertEqual(
                clob_incidents[0]["suggested_command"],
                f"python -m weather.market.market_microstructure raw-refresh --market all --date {TARGET_DATE} --strict",
            )
            risk_events = [
                json.loads(line)
                for line in Path(payload["risk_events_path"]).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(any(row.get("category") == "preflight_remediation" for row in risk_events))

    def test_preflight_remediation_commands_are_executable_cli_commands(self):
        now = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
        payload = build_preflight_remediation(
            {
                "run_id": "run-remediation-cli",
                "target_date": TARGET_DATE,
                "mode": "shadow",
                "status": "BLOCK",
                "markets": [
                    {
                        "market_id": "austin",
                        "event_slug": "",
                        "status": "BLOCK",
                        "gates": [
                            {
                                "name": "active_event",
                                "ok": False,
                                "severity": "block",
                                "detail": "no active current market rows",
                            },
                            {
                                "name": "clob_tokens",
                                "ok": False,
                                "severity": "block",
                                "detail": "clob_tokens.csv has no rows",
                            },
                            {
                                "name": "source_status_degradation",
                                "ok": False,
                                "severity": "block",
                                "detail": "source-status degradation blocks trading evidence",
                            },
                        ],
                    }
                ],
            },
            now,
        )

        commands = {row["gate"]: row["suggested_command"] for row in payload["incidents"]}
        self.assertEqual(
            commands["active_event"],
            f"python -m weather.market.market_microstructure capture --market all --date {TARGET_DATE}",
        )
        self.assertEqual(
            commands["clob_tokens"],
            f"python -m weather.market.market_microstructure capture --market all --date {TARGET_DATE}",
        )
        self.assertEqual(
            commands["source_status_degradation"],
            "python -m weather.collection.snapshot_tracker --backfill-source-status --overwrite-source-status",
        )
        self.assertFalse(any("refresh-tokens" in command for command in commands.values()))

    def test_preflight_remediation_marks_counted_clob_gap_nonrepairable_same_day(self):
        now = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
        payload = build_preflight_remediation(
            {
                "run_id": "run-clob-gap",
                "target_date": TARGET_DATE,
                "mode": "shadow",
                "status": "WARN",
                "markets": [
                    {
                        "market_id": "austin",
                        "event_slug": "highest-temperature-in-austin-on-june-14-2026",
                        "status": "STALE",
                        "folder": "snapshots/highest-temperature-in-austin-on-june-14-2026",
                        "book_audit": {
                            "gaps_over_threshold": 1,
                            "max_counted_gap_seconds": 1168.7,
                            "last_capture_utc": "2026-06-14T16:00:00+00:00",
                        },
                        "gates": [
                            {
                                "name": "clob_freshness",
                                "ok": False,
                                "severity": "stale",
                                "detail": "1 gaps over 177s (max 1168.7s)",
                            }
                        ],
                    }
                ],
            },
            now,
        )

        incident = payload["incidents"][0]
        self.assertEqual(incident["root_cause"], "clob_book_tape_gap_over_threshold")
        self.assertFalse(incident["recoverable_same_day"])
        self.assertFalse(incident["can_still_count_live_forward_day"])
        self.assertEqual(
            incident["suggested_command"],
            f"python -m weather.market.market_microstructure audit --strict --date {TARGET_DATE}",
        )

    def test_preflight_recovery_closeout_records_commands_and_reruns_mm_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root, stale_book=True)
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
                run_id="needs-repair",
                now=NOW,
            )
            self.assertEqual(payload["preflight_status"], "STALE")

            folder = snapshots_root / "highest-temperature-in-atlanta-on-june-14-2026"
            fresh_book_time = "2026-06-14T16:00:20+00:00"
            clob_rows = read_csv(folder / "clob_features_long.csv")
            for row in clob_rows:
                row["clob_book_captured_at_utc"] = fresh_book_time
                row["clob_book_age_seconds"] = "10.0"
            write_csv(folder / "clob_features_long.csv", list(clob_rows[0].keys()), clob_rows)
            book_rows = read_csv(folder / "order_books_summary.csv")
            for row in book_rows:
                row["captured_at_utc"] = fresh_book_time
                row["captured_at_local"] = fresh_book_time
                row["book_time_utc"] = fresh_book_time
            write_csv(folder / "order_books_summary.csv", list(book_rows[0].keys()), book_rows)

            closeout = close_out_preflight_recovery(
                payload["run_folder"],
                execute_remediation=False,
                now="2026-06-14T16:00:30+00:00",
            )

            self.assertEqual(closeout["status"], "RECOVERED")
            self.assertTrue(closeout["recovered"])
            self.assertTrue(Path(payload["run_folder"], "preflight_recovery_closeout.json").exists())
            self.assertTrue(Path(payload["run_folder"], "post_repair_preflight.json").exists())
            self.assertTrue(closeout["command_results"])
            self.assertEqual(closeout["command_results"][0]["action"], "skipped")
            self.assertIn("dry-run closeout", closeout["command_results"][0]["skip_reason"])
            self.assertIn(
                f"python -m weather.market.market_microstructure raw-refresh --market all --date {TARGET_DATE} --strict",
                [row["suggested_command"] for row in closeout["command_results"]],
            )
            self.assertEqual(closeout["post_repair_run"]["preflight_status"], "PASS")
            self.assertTrue(closeout["post_repair_run"]["counts_toward_live_forward_gate"])

            original_summary = json.loads(
                Path(payload["run_folder"], "run_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(original_summary["preflight_recovery_closeout"]["status"], "RECOVERED")
            self.assertEqual(
                original_summary["preflight_recovery_closeout_path"],
                str(Path(payload["run_folder"], "preflight_recovery_closeout.json")),
            )

    def test_live_forward_gate_explains_fresh_observation_but_stale_clob_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root, stale_book=True)
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
                run_id="live-gate-run",
                now=NOW,
            )

            gate = json.loads(Path(payload["live_forward_gate_path"]).read_text(encoding="utf-8"))
            market = gate["markets"][0]
            first_failure = market["first_failing_gate"]
            countability = market["countability"]

            self.assertEqual(payload["preflight_status"], "STALE")
            self.assertEqual(payload["quote_permission_rows"], 0)
            self.assertFalse(payload["counts_toward_live_forward_gate"])
            self.assertEqual(gate["status"], "BLOCK")
            self.assertEqual(first_failure["name"], "clob_freshness")
            self.assertEqual(first_failure["owner"], "CLOB book supervisor")
            self.assertEqual(first_failure["last_good_timestamp"], "2026-06-14T15:00:00+00:00")
            self.assertEqual(first_failure["stale_threshold_seconds"], 120.0)
            self.assertTrue(countability["model_review_evidence"]["counts"])
            self.assertFalse(countability["paper_trading_evidence"]["counts"])
            self.assertIn("clob_freshness", countability["paper_trading_evidence"]["blocking_gates"])
            self.assertFalse(countability["live_trade_permission_evidence"]["counts"])
            self.assertIn("mode_not_live_pilot", countability["live_trade_permission_evidence"]["blocking_gates"])
            self.assertEqual(
                payload["live_forward_gate"]["evidence"]["model_review_evidence"]["countable_market_count"],
                1,
            )

    def test_after_window_paper_run_blocks_evidence_countability_even_when_raw_gate_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root, promotion = write_market_fixture(root)
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
                run_id="post-window-run",
                now="2026-06-15T00:31:18+00:00",
                policy_config={
                    "max_model_age_seconds": 100000.0,
                    "max_book_age_seconds": 100000.0,
                    "max_watcher_age_seconds": 100000.0,
                },
            )

            gate = json.loads(Path(payload["live_forward_gate_path"]).read_text(encoding="utf-8"))
            report = Path(payload["run_report_path"]).read_text(encoding="utf-8")

            self.assertEqual(payload["evidence_mode"], "post_settlement_evaluation")
            self.assertFalse(payload["counts_toward_live_forward_gate"])
            self.assertTrue(payload["live_forward_gate_counts_without_evidence_mode"])
            self.assertEqual(payload["live_forward_gate_status"], "BLOCK")
            self.assertEqual(gate["status_without_evidence_mode"], "PASS")
            self.assertEqual(gate["status"], "BLOCK")
            self.assertTrue(gate["counts_toward_live_forward_gate_without_evidence_mode"])
            self.assertFalse(gate["counts_toward_live_forward_gate"])
            self.assertEqual(gate["evidence_mode_gate"]["evidence_mode"], "post_settlement_evaluation")
            self.assertIn("after active-day evidence window", gate["evidence_mode_gate"]["detail"])
            self.assertIn("- Evidence mode: `post_settlement_evaluation`", report)
            self.assertIn("- Counts toward live-forward gate: `false`", report)

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
            diagnostics = payload["preflight_diagnostics"]
            self.assertEqual(diagnostics["status_counts"], {"BLOCK": 1})
            self.assertEqual(diagnostics["blocked_market_count"], 1)
            blocking_reasons = {
                item["reason"]
                for item in diagnostics["top_blocking_reasons"]
            }
            self.assertIn("no active current market rows", blocking_reasons)
            self.assertIn("missing current snapshot/model rows", blocking_reasons)
            failing_gates = {
                item["gate"]
                for item in diagnostics["top_failing_gates"]
            }
            self.assertIn("active_event", failing_gates)
            self.assertIn("snapshot_model_rows", failing_gates)
            self.assertEqual(payload["operator_alert"]["top_preflight_failing_gate"], "active_event")

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
            self.assertTrue(all("known_edge_match_hour_utc" in row for row in rows))
            self.assertEqual({row["known_edge_match_hour_utc"] for row in rows}, {"15"})
            self.assertEqual({row["known_edge_match_band_type"] for row in rows}, {"eq"})
            self.assertEqual({row["known_edge_match_source_fresh"] for row in rows}, {"true"})
            self.assertEqual({row["known_edge_match_source_freshness_state"] for row in rows}, {"all_fresh"})
            self.assertTrue(all("known_edge_match_band_distance_bucket" in row for row in rows))
            self.assertTrue(all("known_edge_match_casebook_taxonomy" in row for row in rows))
            self.assertTrue(all("known_edge_match_book_imbalance_bucket" in row for row in rows))


if __name__ == "__main__":
    unittest.main()
