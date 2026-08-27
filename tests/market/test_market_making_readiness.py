import json
import os
from pathlib import Path

from weather.market.market_making_readiness import (
    SCHEMA_VERSION as READINESS_SCHEMA_VERSION,
    build_readiness_snapshot,
    find_latest_paper_score,
    render_readiness_report,
)
from weather.market.market_making_preflight import (
    platform_account_snapshot_sha256,
    stage1_lifecycle_bundle_sha256,
)
from weather.market.market_making_run_constants import (
    PLATFORM_VERIFICATION_SCHEMA_VERSION,
)


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def stage1_lifecycle_bundle():
    bootstrap_hash = "a" * 64

    def probe(mode, order_id):
        return {
            "schema_version": "mm_live_lifecycle_probe_v0.3",
            "status": "PASS",
            "completed_at_utc": "2026-06-26T16:00:00+00:00",
            "platform": "polymarket_global",
            "settlement_unit": "pUSD",
            "cancellation_mode": mode,
            "bootstrap_schema_version": "mm_platform_bootstrap_v0.4",
            "bootstrap_sha256": bootstrap_hash,
            "condition_id": "0x" + "b" * 64,
            "token_id": "12345",
            "heartbeat_acknowledged": True,
            "submit_boundary_heartbeat_acknowledged": True,
            "submit_boundary_market_rules_verified": True,
            "submit_boundary_geography_before_heartbeat_verified": True,
            "post_sign_order_placement_boundary_verified": True,
            "candidate_fee_rate": 0.05,
            "current_fee_rate_bps": 500,
            "candidate_neg_risk": False,
            "current_neg_risk": False,
            "starting_zero_open_orders_verified": True,
            "starting_zero_positions_verified": True,
            "submit_collateral_balance_usdc": 100,
            "submit_collateral_allowance_usdc": 100,
            "submit_collateral_snapshot_sha256": ("1" if mode == "cancel_all" else "2") * 64,
            "post_cancel_collateral_snapshot_sha256": ("1" if mode == "cancel_all" else "2") * 64,
            "collateral_no_fill_reconciliation_verified": True,
            "order_notional_usdc": 0.05,
            "order_id": order_id,
            "placement_status": "live",
            "open_order_observed": True,
            "authoritative_user_event_observed": True,
            "cancellation_observed": True,
            "cancellation_elapsed_seconds": 0 if mode == "cancel_all" else 15,
            "terminal_user_event_observed": True,
            "no_trade_lifecycle_event_observed": True,
            "terminal_rest_order_verified": True,
            "terminal_rest_order_sha256": ("3" if mode == "cancel_all" else "4") * 64,
            "terminal_rest_zero_matched_verified": True,
            "account_trades_rest_verified": True,
            "scoped_account_trade_count": 0,
            "post_cancel_quiescence_seconds": 2.0,
            "cancel_response_present": mode == "cancel_all",
            "zero_open_orders_verified": True,
            "zero_positions_verified": True,
            "secret_values_redacted": True,
            "journal_path": f"stage1-{mode}.jsonl",
            "journal_sha256": ("e" if mode == "cancel_all" else "f") * 64,
            "user_stream_journal_path": f"stage1-{mode}-user-stream.jsonl",
            "user_stream_journal_sha256": ("c" if mode == "cancel_all" else "d") * 64,
            "cleanup_final_user_stream_journal_sha256": (
                "c" if mode == "cancel_all" else "d"
            )
            * 64,
            "user_stream_journal_row_count": 8,
            "user_stream_scoped_order_event_count": 2,
        }

    bundle = {
        "schema_version": "mm_stage1_lifecycle_bundle_v0.3",
        "status": "PASS",
        "created_at_utc": "2026-06-26T16:00:00+00:00",
        "platform": "polymarket_global",
        "settlement_unit": "pUSD",
        "bootstrap_schema_version": "mm_platform_bootstrap_v0.4",
        "bootstrap_sha256": bootstrap_hash,
        "condition_id": "0x" + "b" * 64,
        "token_id": "12345",
        "funder_address": "0x0000000000000000000000000000000000000001",
        "requested_budget_usdc": 10,
        "lifecycle_results": {
            "cancel_all": probe("cancel_all", "cancel-order"),
            "dead_man": probe("dead_man", "dead-man-order"),
        },
        "journal_evidence": {
            "cancel_all": {
                "path": "stage1-cancel_all.jsonl",
                "sha256": "e" * 64,
                "row_count": 18,
            },
            "dead_man": {
                "path": "stage1-dead_man.jsonl",
                "sha256": "f" * 64,
                "row_count": 18,
            },
        },
        "user_stream_journal_evidence": {
            "cancel_all": {
                "path": "stage1-cancel_all-user-stream.jsonl",
                "sha256": "c" * 64,
                "row_count": 8,
                "scoped_order_event_count": 2,
                "terminal_stream_stopped_verified": True,
            },
            "dead_man": {
                "path": "stage1-dead_man-user-stream.jsonl",
                "sha256": "d" * 64,
                "row_count": 8,
                "scoped_order_event_count": 2,
                "terminal_stream_stopped_verified": True,
            },
        },
        "derived_platform_evidence": {
            "starting_open_orders_rest_verified": True,
            "order_update_verified": True,
            "fill_event_verified": False,
            "no_fill_lifecycle_verified": True,
            "final_state_reconciliation_verified": True,
            "terminal_order_rest_verified": True,
            "account_trades_rest_verified": True,
            "final_user_stream_journals_verified": True,
            "action_time_collateral_verified": True,
            "no_fill_collateral_reconciliation_verified": True,
            "cancel_all_request_verified": True,
            "cancel_all_zero_open_orders_verified": True,
            "dead_man_automatic_cancel_verified": True,
            "heartbeat_acknowledgment_verified": True,
        },
        "secret_values_redacted": True,
    }
    bundle["bundle_sha256"] = stage1_lifecycle_bundle_sha256(bundle)
    return bundle


def platform_verification(target_date="2026-06-26"):
    account_snapshot = {
        "balance_allowance_verified": True,
        "collateral_balance_usdc": 100,
        "collateral_allowance_usdc": 100,
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
    lifecycle_bundle = stage1_lifecycle_bundle()
    return {
        "schema_version": "mm_platform_verification_v0.6",
        "status": "PASS",
        "verified_for_target_date": target_date,
        "verified_at_utc": "2026-06-26T16:00:00+00:00",
        "docs_checked_at_utc": "2026-06-26T16:00:00+00:00",
        "max_age_hours": 24,
        "platform": "polymarket_global",
        "international_platform_confirmed": True,
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
            "distribution": "polymarket-client",
            "version": "0.6.0",
            "exact_version_verified": True,
            "wallet_model_probe_verified": True,
        },
        "allowances_verified": True,
        "balance_verified": True,
        "collateral_balance_usdc": 100,
        "collateral_allowance_usdc": 100,
        "account_snapshot_sha256": account_snapshot["snapshot_sha256"],
        "open_order_count": 0,
        "account_snapshot": account_snapshot,
        "stage1_lifecycle_bundle_sha256": lifecycle_bundle["bundle_sha256"],
        "stage1_lifecycle_bundle": lifecycle_bundle,
        "fees_verified": True,
        "fee_model": {"taker_fee_rate": 0.05, "maker_rebate_rate": 0.25},
        "reward_rules_verified": True,
        "rebate_rules_verified": True,
        "order_semantics_verified": True,
        "maker_only_order_field": "postOnly",
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
            "terminal_order_rest_verified": True,
            "account_trades_rest_verified": True,
            "final_user_stream_journals_verified": True,
            "action_time_collateral_verified": True,
            "no_fill_collateral_reconciliation_verified": True,
        },
        "cancel_all_verified": True,
        "cancel_all": {
            "request_verified": True,
            "zero_open_orders_verified": True,
        },
        "dead_man_heartbeat": {
            "endpoint": "/heartbeats",
            "endpoint_verified": True,
            "request_body_absent_verified": True,
            "two_acknowledgments_verified": True,
            "acknowledgment_count": 2,
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
        "pilot_wallet_max_funding_usdc": 100,
        "backend_only_signing": True,
        "private_key_storage": "external_secret_store",
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
            "https://docs.polymarket.com/trading/fees",
            "https://docs.polymarket.com/concepts/pusd",
        ],
    }


def paper_payload(**overrides):
    summary = {
        "target_date": "2026-06-26",
        "quote_permission_rows": 4,
        "quote_legs": 8,
        "live_trade_permission_rows": 0,
        "gate_status": "OPEN",
        "gate_status_scope": "paper_day_collection_and_exchange_economics_not_live_capital",
        "live_capital_gate_status": "NOT_EVALUATED_BY_MM_PAPER",
        "live_capital_gate_reason": (
            "use weather.market.market_making_readiness; fill evidence, live-forward countability, "
            "operator, and platform gates remain separate"
        ),
        "fill_evidence_completeness_status": "PASS",
        "fill_evidence_promotion_grade": True,
        "fill_evidence_blockers": [],
        "anti_overfit": {
            "locked_policy_params": True,
            "policy_hashes": ["policy-a"],
            "live_forward_days": [
                "2026-06-13",
                "2026-06-14",
                "2026-06-15",
                "2026-06-16",
                "2026-06-17",
                "2026-06-18",
                "2026-06-19",
                "2026-06-20",
                "2026-06-21",
                "2026-06-22",
                "2026-06-23",
                "2026-06-24",
                "2026-06-25",
                "2026-06-26",
            ],
        },
        "pnl": {"net_pnl_after_fees_incentives_usdc": 1.25},
        "unresolved_resting_quote_count": 0,
        "actual_payout_evidence": True,
        "counterfactual_reward_usdc": 0,
        "exchange_economics_gate_status": "PASS",
        "exchange_economics_snapshot_id": "xecon-test",
    }
    summary.update(overrides)
    target_date = summary.get("target_date")
    return {
        "summary": summary,
        "run_configs": {
            "synthetic-run": {
                "target_date": target_date,
                "evidence_classification": {"target_date": target_date},
            }
        },
    }


def preflight_payload(status="PASS", failing_gate=None):
    gate_names = [
        "active_event",
        "event_metadata_validation",
        "exchange_economics_gate",
        "snapshot_model_rows",
        "model_freshness",
        "source_status_rows",
        "source_status_fresh",
        "source_status_degradation",
        "clob_discovery",
        "clob_tokens",
        "clob_books",
        "clob_features",
        "clob_freshness",
        "reward_metadata",
        "observation_trigger",
        "promotion_state",
    ]
    markets = []
    for market_id in ["dallas", "austin"]:
        gates = []
        for gate_name in gate_names:
            failed = failing_gate == gate_name and market_id == "dallas"
            gates.append({
                "name": gate_name,
                "ok": not failed,
                "severity": "stale" if failed else "pass",
                "detail": "synthetic stale gate" if failed else "ok",
            })
        markets.append({
            "market_id": market_id,
            "status": "STALE" if failing_gate and market_id == "dallas" else "PASS",
            "gates": gates,
        })
    return {
        "status": status,
        "markets": markets,
        "observation_status": {
            "fresh": True,
            "heartbeat_ok": True,
            "last_heartbeat": "2026-06-26T16:59:00+00:00",
        },
    }


def status_payload():
    return {
        "status": "started",
        "target_date": "2026-06-26",
        "evidence_mode": "active_day_live_forward",
        "current_counts_toward_live_forward_gate": True,
        "live_forward_gate_status": "PASS",
        "operator_report": {
            "supervisor_state": "RUNNING",
            "supervisor_action": "noop",
            "supervisor_runtime_identity_matches_current": True,
            "live_forward_gate_status": "PASS",
            "current_counts_toward_live_forward_gate": True,
        },
    }


def test_live_readiness_snapshot_blocks_current_no_go_evidence(tmp_path):
    live_readiness_path = tmp_path / "missing_live_readiness.json"
    platform_path = write_json(tmp_path / "platform.json", {"schema_version": "mm_platform_verification_v0.1"})

    payload = build_readiness_snapshot(
        status_payload={
            "target_date": "2026-06-26",
            "evidence_mode": "post_settlement_evaluation",
            "current_counts_toward_live_forward_gate": False,
            "live_forward_gate_status": "BLOCK",
            "operator_report": {
                "supervisor_state": "STALE_CODE",
                "supervisor_action": "backoff",
                "supervisor_runtime_identity_matches_current": False,
                "latest_quote_rows": 132,
                "latest_quote_permission_rows": 4,
            },
        },
        paper_payload=paper_payload(
            quote_permission_rows=17,
            quote_blocker_diagnostics={
                "blocked_rows": 33,
                "blocked_fraction": 1.0,
                "reason_counts": {
                    "NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED": 25,
                    "NO_QUOTE_MISSING_BOOK": 8,
                },
                "event_gate_suppressed_rows": 0,
                "stale_input_rows": 0,
            },
            fill_evidence_completeness_status="BLOCK",
            fill_evidence_promotion_grade=False,
            fill_evidence_blockers=["missing_size_trade_rows", "unresolved_resting_quotes"],
            quote_uptime={
                "quote_permission_market_counts": {"austin": 4, "dallas": 7},
                "top_quote_permission_cells": [
                    {
                        "market_id": "dallas",
                        "range_label": "94-95 F",
                        "known_edge_permission": "harvest_only",
                        "promotion_state": "SHADOW",
                        "reason_code": "QUOTE_HARVEST_MID",
                        "rows": 1,
                    }
                ],
            },
            paper_score_freshness_status="NO_ACTIVE_DAY",
            conservative_fills=0,
            queue_estimated_fill_legs=1,
            missing_size_trade_rows=400,
            missing_book_queue_legs=2,
            total_reward_score=20.559525,
            counterfactual_reward_usdc=176.767745,
            counterfactual_reward_status="COUNTERFACTUAL_ONLY",
            score_at_or_above_target_size=False,
            anti_overfit={"locked_policy_params": False, "policy_hashes": ["a", "b"], "live_forward_days": []},
            pnl={"net_pnl_after_fees_incentives_usdc": 0.0},
            unresolved_resting_quote_count=34,
            actual_payout_evidence=False,
        ),
        latest_run_summary={
            "preflight_status": "WARN",
            "known_edge_map": {
                "path": str(tmp_path / "known_edge.json"),
                "exists": True,
                "schema_version": "mm_known_edge_map_v0.2",
                "record_count": 17,
                "diagnostic_only": False,
            },
            "preflight_diagnostics": {
                "stale_market_count": 1,
                "blocked_market_count": 0,
                "top_failing_gates": [{"gate": "model_freshness", "market_count": 1}],
            },
            "first_failing_gate": "policy",
            "root_cause_class": "policy_no_edge",
            "reason_counts": {
                "NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED": 25,
                "NO_QUOTE_MISSING_BOOK": 8,
            },
            "quote_outcome": {
                "status": "policy_blocked",
                "reason": "quote policy emitted no quote permissions",
            },
        },
        preflight_payload=preflight_payload(status="WARN", failing_gate="model_freshness"),
        live_readiness_path=live_readiness_path,
        platform_verification_path=platform_path,
        now="2026-06-26T17:00:00+00:00",
    )

    assert payload["status"] == "BLOCK"
    assert payload["schema_version"] == READINESS_SCHEMA_VERSION == "mm_live_readiness_v0.3"
    assert payload["live_capital_permission"] is False
    blockers = {gate["id"] for gate in payload["blockers"]}
    gate_by_id = {gate["id"]: gate for gate in payload["gates"]}
    assert "latest_preflight_passes" in blockers
    assert gate_by_id["latest_preflight_passes"]["detail"] == "latest selected run preflight is stale or blocked"
    assert "snapshot_model_source_fresh" in blockers
    assert "stale or failing" in gate_by_id["snapshot_model_source_fresh"]["detail"]
    assert "event_metadata_target_date_validated" not in blockers
    assert "clob_capture_and_reward_metadata_fresh" not in blockers
    assert "observation_trigger_fresh" not in blockers
    assert "daily_roll_runtime_identity_current" in blockers
    runtime_gate = gate_by_id["daily_roll_runtime_identity_current"]
    assert "stale or unknown" in runtime_gate["detail"]
    assert "supervisor_state=STALE_CODE" in runtime_gate["detail"]
    assert "supervisor_action=backoff" in runtime_gate["detail"]
    assert runtime_gate["evidence"]["runtime_identity_matches_current"] is False
    assert "active_day_live_forward_evidence" in blockers
    assert "not countable active-day" in gate_by_id["active_day_live_forward_evidence"]["detail"]
    assert "quote_permission_present_in_countable_paper" in blockers
    assert "does not have nonzero quote permissions" in gate_by_id["quote_permission_present_in_countable_paper"]["detail"]
    assert "fill_evidence_complete" in blockers
    assert "incomplete" in gate_by_id["fill_evidence_complete"]["detail"]
    assert "platform_verification_passes" in blockers
    assert "missing, stale, or failing" in gate_by_id["platform_verification_passes"]["detail"]
    assert payload["summary"]["paper_score_quote_permission_rows"] == 17
    assert payload["summary"]["paper_quote_blocked_rows"] == 33
    assert payload["summary"]["paper_quote_blocked_fraction"] == 1.0
    assert payload["summary"]["paper_quote_blocker_reason_counts"] == {
        "NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED": 25,
        "NO_QUOTE_MISSING_BOOK": 8,
    }
    assert payload["summary"]["paper_quote_blocker_event_gate_suppressed_rows"] == 0
    assert payload["summary"]["paper_quote_blocker_stale_input_rows"] == 0
    assert payload["summary"]["paper_quote_permission_market_counts"] == {"austin": 4, "dallas": 7}
    assert payload["summary"]["paper_top_quote_permission_cells"][0]["market_id"] == "dallas"
    assert payload["summary"]["paper_top_quote_permission_cells"][0]["range_label"] == "94-95 F"
    assert payload["summary"]["latest_tick_quote_permission_rows"] == 4
    assert payload["summary"]["latest_tick_first_failing_gate"] == "policy"
    assert payload["summary"]["latest_tick_root_cause_class"] == "policy_no_edge"
    assert payload["summary"]["latest_tick_quote_outcome_status"] == "policy_blocked"
    assert payload["summary"]["latest_tick_reason_counts"] == {
        "NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED": 25,
        "NO_QUOTE_MISSING_BOOK": 8,
    }
    assert payload["summary"]["known_edge_map_path"] == (tmp_path / "known_edge.json").as_posix()
    assert payload["summary"]["known_edge_map_schema_version"] == "mm_known_edge_map_v0.2"
    assert payload["summary"]["known_edge_map_record_count"] == 17
    assert payload["summary"]["known_edge_map_diagnostic_only"] is False
    assert payload["summary"]["paper_score_live_trade_permission_rows"] == 0
    assert payload["summary"]["latest_tick_live_trade_permission_rows"] == 0
    assert payload["summary"]["paper_score_freshness_status"] == "NO_ACTIVE_DAY"
    assert payload["summary"]["live_forward_day_count"] == 0
    assert payload["summary"]["locked_policy_params"] is False
    assert payload["summary"]["fill_evidence_blockers"] == ["missing_size_trade_rows", "unresolved_resting_quotes"]
    assert payload["summary"]["conservative_fills"] == 0
    assert payload["summary"]["queue_estimated_fill_legs"] == 1
    assert payload["summary"]["missing_size_trade_rows"] == 400
    assert payload["summary"]["missing_book_queue_legs"] == 2
    assert payload["summary"]["total_reward_score"] == 20.559525
    assert payload["summary"]["counterfactual_reward_usdc"] == 176.767745
    assert payload["summary"]["counterfactual_reward_status"] == "COUNTERFACTUAL_ONLY"
    assert payload["summary"]["score_at_or_above_target_size"] is False
    next_actions = payload["next_actions"]
    assert next_actions == sorted(next_actions, key=lambda action: (action["priority"], action["gate_id"]))
    assert next_actions[0]["gate_id"] == "latest_preflight_passes"
    assert next_actions[0]["category"] == "data_preflight"
    assert "preflight" in next_actions[0]["safe_next_step"]
    assert any(action["gate_id"] == "operator_live_readiness_file_passes" for action in next_actions)
    platform_action = next(
        action
        for action in next_actions
        if action["gate_id"] == "platform_verification_passes"
    )
    assert PLATFORM_VERIFICATION_SCHEMA_VERSION in platform_action["safe_next_step"]


def test_readiness_snapshot_uses_one_shot_run_summary_for_latest_tick_counts(tmp_path):
    payload = build_readiness_snapshot(
        status_payload={
            "target_date": "2026-06-27",
            "evidence_mode": "operator_drill",
            "current_counts_toward_live_forward_gate": False,
            "live_forward_gate_status": "BLOCK",
        },
        paper_payload=paper_payload(target_date="2026-06-27", quote_permission_rows=23),
        latest_run_summary={
            "target_date": "2026-06-27",
            "preflight_status": "PASS",
            "quote_rows": 132,
            "no_quote_rows": 109,
            "quote_permission_rows": 23,
            "live_trade_permission_rows": 0,
            "root_cause_class": "trading_permissions_emitted",
            "reason_counts": {
                "QUOTE_HARVEST_MID": 23,
                "NO_QUOTE_KNOWN_EDGE_PERMISSION": 88,
            },
            "quote_outcome": {
                "status": "quoted",
                "reason": "quote permissions emitted",
                "row_count": 132,
                "quote_permission_rows": 23,
            },
        },
        preflight_payload=preflight_payload(status="PASS"),
        live_forward_gate={"target_date": "2026-06-27", "status": "BLOCK"},
        live_readiness_path=None,
        platform_verification_path=None,
        now="2026-06-27T07:31:00+00:00",
    )

    assert payload["summary"]["latest_tick_quote_rows"] == 132
    assert payload["summary"]["latest_tick_no_quote_rows"] == 109
    assert payload["summary"]["latest_tick_quote_permission_rows"] == 23
    assert payload["summary"]["latest_tick_live_trade_permission_rows"] == 0
    assert payload["summary"]["latest_tick_quote_outcome_status"] == "quoted"
    assert payload["summary"]["latest_tick_reason_counts"] == {
        "QUOTE_HARVEST_MID": 23,
        "NO_QUOTE_KNOWN_EDGE_PERMISSION": 88,
    }


def test_snapshot_model_source_gate_blocks_source_status_degradation(tmp_path):
    live_readiness_path = write_json(
        tmp_path / "live_readiness.json",
        {
            "account_platform_verified": True,
            "wallet_ready": True,
            "allowance_ready": True,
            "heartbeat_ready": True,
            "user_websocket_ready": True,
            "cancel_all_ready": True,
        },
    )
    platform_path = write_json(tmp_path / "platform.json", platform_verification())

    payload = build_readiness_snapshot(
        status_payload=status_payload(),
        paper_payload=paper_payload(),
        latest_run_summary={
            "preflight_status": "BLOCK",
            "preflight_diagnostics": {
                "stale_market_count": 0,
                "blocked_market_count": 1,
                "top_failing_gates": [
                    {
                        "gate": "source_status_degradation",
                        "market_count": 1,
                        "detail": "source-status degradation blocks trading evidence",
                    }
                ],
            },
        },
        preflight_payload=preflight_payload(status="BLOCK", failing_gate="source_status_degradation"),
        live_readiness_path=live_readiness_path,
        platform_verification_path=platform_path,
        now="2026-06-26T17:00:00+00:00",
    )

    blockers = {gate["id"] for gate in payload["blockers"]}
    gate_by_id = {gate["id"]: gate for gate in payload["gates"]}
    source_gate = gate_by_id["snapshot_model_source_fresh"]

    assert payload["status"] == "BLOCK"
    assert "latest_preflight_passes" in blockers
    assert "snapshot_model_source_fresh" in blockers
    assert source_gate["ok"] is False
    assert source_gate["evidence"]["failing_count"] == 1
    assert source_gate["evidence"]["failing"][0]["gate"] == "source_status_degradation"
    assert "source_status_degradation" in source_gate["evidence"]["gate_names"]
    assert payload["summary"]["source_status_blocker_status"] == "BLOCK"
    assert payload["summary"]["source_status_blocker_root_cause_class"] == "source_status_degradation"
    assert payload["summary"]["source_status_blocked_market_count"] == 1
    assert payload["summary"]["source_status_repair_command"] == (
        "python -m weather.collection.snapshot_tracker "
        "--backfill-source-status --overwrite-source-status"
    )
    source_actions = [
        action for action in payload["next_actions"]
        if action["gate_id"] in {"latest_preflight_passes", "snapshot_model_source_fresh"}
    ]
    assert source_actions
    assert all("backfill-source-status" in action["safe_next_step"] for action in source_actions)


def test_source_status_blocker_aggregates_settlement_auth_failures(tmp_path):
    live_readiness_path = write_json(
        tmp_path / "live_readiness.json",
        {
            "account_platform_verified": True,
            "wallet_ready": True,
            "allowance_ready": True,
            "heartbeat_ready": True,
            "user_websocket_ready": True,
            "cancel_all_ready": True,
        },
    )
    platform_path = write_json(tmp_path / "platform.json", platform_verification())

    payload = build_readiness_snapshot(
        status_payload=status_payload(),
        paper_payload=paper_payload(),
        latest_run_summary={
            "preflight_status": "BLOCK",
            "preflight_diagnostics": {
                "stale_market_count": 0,
                "blocked_market_count": 3,
                "top_failing_gates": [
                    {
                        "gate": "source_status_degradation",
                        "market_count": 3,
                        "markets": ["austin", "dallas", "houston"],
                        "detail": (
                            "source-status degradation blocks trading evidence: "
                            "blocking_families=3 settlement_auth_failures=1"
                        ),
                    }
                ],
            },
        },
        preflight_payload=preflight_payload(status="BLOCK", failing_gate="source_status_degradation"),
        live_readiness_path=live_readiness_path,
        platform_verification_path=platform_path,
        now="2026-06-26T17:00:00+00:00",
    )

    summary = payload["summary"]
    assert summary["source_status_blocker_root_cause_class"] == "settlement_source_auth_failure"
    assert summary["source_status_blocked_market_count"] == 3
    assert summary["source_status_settlement_auth_failures"] == 3
    assert summary["source_status_settlement_auth_failures_per_market"] == 1
    assert summary["source_status_settlement_auth_failure_market_count"] == 3
    assert not any("credential" in key for key in summary)
    assert summary["source_status_degradation_failed_markets"] == ["austin", "dallas", "houston"]
    assert any(
        "verify free-source replacement coverage" in action["safe_next_step"]
        for action in payload["next_actions"]
    )


def test_snapshot_model_source_summary_counts_gate_failures(tmp_path):
    live_readiness_path = write_json(
        tmp_path / "live_readiness.json",
        {
            "account_platform_verified": True,
            "wallet_ready": True,
            "allowance_ready": True,
            "heartbeat_ready": True,
            "user_websocket_ready": True,
            "cancel_all_ready": True,
        },
    )
    platform_path = write_json(tmp_path / "platform.json", platform_verification())
    preflight = preflight_payload(status="BLOCK")
    for market in preflight["markets"]:
        gates = {gate["name"]: gate for gate in market["gates"]}
        if market["market_id"] in {"dallas", "austin"}:
            market["status"] = "BLOCK"
            gates["source_status_degradation"].update({
                "ok": False,
                "severity": "missing",
                "detail": "source-status degradation blocks trading evidence",
            })
        if market["market_id"] == "dallas":
            gates["model_freshness"].update({
                "ok": False,
                "severity": "stale",
                "detail": "current model snapshot is stale or timestamp is missing",
            })

    payload = build_readiness_snapshot(
        status_payload=status_payload(),
        paper_payload=paper_payload(),
        latest_run_summary={
            "preflight_status": "BLOCK",
            "preflight_diagnostics": {
                "stale_market_count": 0,
                "blocked_market_count": 2,
                "top_failing_gates": [
                    {
                        "gate": "source_status_degradation",
                        "market_count": 2,
                        "markets": ["austin", "dallas"],
                        "detail": "source-status degradation blocks trading evidence",
                    },
                    {
                        "gate": "model_freshness",
                        "market_count": 1,
                        "markets": ["dallas"],
                        "detail": "current model snapshot is stale or timestamp is missing",
                    },
                ],
            },
            "preflight_remediation": {
                "status": "BLOCK",
                "root_cause_counts": {
                    "observation_trigger_blocked_markets": 1,
                    "source_status_degradation_blocked": 2,
                },
                "owner_counts": {
                    "observation-trigger supervisor": 1,
                    "snapshot source-status writer / optional provider source": 2,
                },
            },
        },
        preflight_payload=preflight,
        live_readiness_path=live_readiness_path,
        platform_verification_path=platform_path,
        now="2026-06-26T17:00:00+00:00",
    )

    gate_by_id = {gate["id"]: gate for gate in payload["gates"]}
    evidence = gate_by_id["snapshot_model_source_fresh"]["evidence"]
    summary = payload["summary"]

    assert evidence["failing_count"] == 3
    assert evidence["failing_gate_counts"] == {
        "model_freshness": 1,
        "source_status_degradation": 2,
    }
    assert evidence["failing_market_counts"] == {
        "model_freshness": 1,
        "source_status_degradation": 2,
    }
    assert evidence["failing_markets"] == {
        "model_freshness": ["dallas"],
        "source_status_degradation": ["austin", "dallas"],
    }
    assert summary["snapshot_model_source_failing_count"] == 3
    assert summary["snapshot_model_source_failing_gate_counts"] == evidence["failing_gate_counts"]
    assert summary["snapshot_model_source_failing_market_counts"] == evidence["failing_market_counts"]
    assert summary["snapshot_model_source_failing_markets"] == evidence["failing_markets"]
    assert summary["model_freshness_failed_market_count"] == 1
    assert summary["model_freshness_failed_markets"] == ["dallas"]
    assert summary["source_status_degradation_failed_market_count"] == 2
    assert summary["source_status_degradation_failed_markets"] == ["austin", "dallas"]
    assert summary["preflight_remediation_status"] == "BLOCK"
    assert summary["preflight_remediation_root_cause_counts"] == {
        "observation_trigger_blocked_markets": 1,
        "source_status_degradation_blocked": 2,
    }
    assert summary["observation_trigger_runtime_root_cause_counts"] == {
        "observation_trigger_blocked_markets": 1,
    }


def test_readiness_snapshot_downgrades_legacy_zero_quote_fill_pass(tmp_path):
    live_readiness_path = write_json(
        tmp_path / "live_readiness.json",
        {
            "account_platform_verified": True,
            "wallet_ready": True,
            "allowance_ready": True,
            "heartbeat_ready": True,
            "user_websocket_ready": True,
            "cancel_all_ready": True,
        },
    )
    platform_path = write_json(tmp_path / "platform.json", platform_verification(target_date="2026-06-27"))

    payload = build_readiness_snapshot(
        status_payload={
            **status_payload(),
            "target_date": "2026-06-27",
        },
        paper_payload=paper_payload(
            target_date="2026-06-27",
            quote_permission_rows=0,
            quote_legs=0,
            fill_evidence_completeness_status="PASS",
            fill_evidence_promotion_grade=True,
            fill_evidence_blockers=[],
        ),
        preflight_payload=preflight_payload(status="PASS"),
        live_readiness_path=live_readiness_path,
        platform_verification_path=platform_path,
        now="2026-06-27T17:00:00+00:00",
    )

    gate_by_id = {gate["id"]: gate for gate in payload["gates"]}
    fill_gate = gate_by_id["fill_evidence_complete"]
    assert payload["status"] == "BLOCK"
    assert fill_gate["ok"] is False
    assert fill_gate["evidence"]["fill_evidence_vacuous"] is True
    assert fill_gate["evidence"]["fill_evidence_effective_promotion_grade"] is False
    assert payload["summary"]["fill_evidence_vacuous"] is True
    assert payload["summary"]["fill_evidence_effective_promotion_grade"] is False
    assert payload["summary"]["fill_evidence_quote_legs"] == 0


def test_readiness_snapshot_blocks_mismatched_status_and_paper_target_dates(tmp_path):
    payload = build_readiness_snapshot(
        status_payload={
            **status_payload(),
            "target_date": "2026-06-26",
        },
        paper_payload=paper_payload(target_date="2026-06-27"),
        preflight_payload=preflight_payload(),
        live_readiness_path=None,
        platform_verification_path=None,
        now="2026-06-27T12:00:00+00:00",
    )

    blockers = {gate["id"] for gate in payload["blockers"]}
    gate_by_id = {gate["id"]: gate for gate in payload["gates"]}
    assert "readiness_inputs_target_date_aligned" in blockers
    gate = gate_by_id["readiness_inputs_target_date_aligned"]
    assert gate["evidence"]["status_target_date"] == "2026-06-26"
    assert gate["evidence"]["paper_score_target_dates"] == ["2026-06-27"]
    assert gate["evidence"]["known_target_dates"] == ["2026-06-26", "2026-06-27"]
    assert payload["next_actions"][0]["gate_id"] == "readiness_inputs_target_date_aligned"


def test_readiness_snapshot_blocks_prior_target_daily_roll_status(tmp_path):
    status = {
        **status_payload(),
        "target_date": "2026-06-26",
        "evidence_mode": "post_settlement_evaluation",
        "current_counts_toward_live_forward_gate": False,
        "daily_roll_supervisor": {
            "state": "SCHEDULED_WAIT",
            "action": "scheduled_wait",
            "target_date": "2026-06-26",
            "expected_target_date": "2026-06-27",
            "start_time_gate": {
                "allowed": False,
                "start_after_local_time": "19:30",
                "reason": "before_daily_start_time",
            },
        },
    }

    payload = build_readiness_snapshot(
        status_payload=status,
        paper_payload=paper_payload(target_date="2026-06-26"),
        preflight_payload=preflight_payload(),
        live_readiness_path=None,
        platform_verification_path=None,
        now="2026-06-27T06:30:00+00:00",
    )

    blockers = {gate["id"] for gate in payload["blockers"]}
    gate_by_id = {gate["id"]: gate for gate in payload["gates"]}
    assert "readiness_inputs_target_date_aligned" not in blockers
    assert "daily_roll_target_date_current" in blockers
    gate = gate_by_id["daily_roll_target_date_current"]
    assert gate["evidence"]["status_target_date"] == "2026-06-26"
    assert gate["evidence"]["expected_target_date"] == "2026-06-27"
    assert gate["evidence"]["start_time_gate"]["start_after_local_time"] == "19:30"
    assert payload["next_actions"][0]["gate_id"] == "daily_roll_target_date_current"


def test_readiness_snapshot_surfaces_stale_heartbeat_runtime_liveness(tmp_path):
    live_readiness_path = write_json(
        tmp_path / "live_readiness.json",
        {
            "account_platform_verified": True,
            "wallet_ready": True,
            "allowance_ready": True,
            "heartbeat_ready": True,
            "user_websocket_ready": True,
            "cancel_all_ready": True,
        },
    )
    platform_path = write_json(tmp_path / "platform.json", platform_verification())
    status = {
        **status_payload(),
        "status": "idle_process",
        "action": "blocked_restart_required",
        "root_cause_class": "stale_heartbeat_metadata",
        "artifact_liveness": {
            "ok": False,
            "status": "STALE_HEARTBEAT_METADATA",
            "root_cause_class": "stale_heartbeat_metadata",
            "detail": "run_summary.json is stale",
        },
        "daily_roll_supervisor": {
            "state": "SCHEDULED_WAIT",
            "action": "scheduled_wait",
            "target_date": "2026-06-26",
            "expected_target_date": "2026-06-26",
        },
        "operator_report": {
            "supervisor_state": "SCHEDULED_WAIT",
            "supervisor_action": "scheduled_wait",
            "supervisor_runtime_identity_matches_current": True,
            "restart_recommended": True,
            "restart_reason": "stale_heartbeat_metadata",
            "live_forward_gate_status": "PASS",
            "current_counts_toward_live_forward_gate": True,
        },
    }

    payload = build_readiness_snapshot(
        status_payload=status,
        paper_payload=paper_payload(),
        preflight_payload=preflight_payload(),
        live_readiness_path=live_readiness_path,
        platform_verification_path=platform_path,
        now="2026-06-26T17:00:00+00:00",
    )

    gate_by_id = {gate["id"]: gate for gate in payload["gates"]}
    runtime_gate = gate_by_id["daily_roll_runtime_identity_current"]
    assert payload["status"] == "BLOCK"
    assert runtime_gate["ok"] is False
    assert "daily_roll_action=blocked_restart_required" in runtime_gate["detail"]
    assert "artifact_liveness_status=STALE_HEARTBEAT_METADATA" in runtime_gate["detail"]
    assert "operator_restart_reason=stale_heartbeat_metadata" in runtime_gate["detail"]
    assert "run_summary.json is stale" in runtime_gate["detail"]
    assert payload["summary"]["daily_roll_action"] == "blocked_restart_required"
    assert payload["summary"]["artifact_liveness_status"] == "STALE_HEARTBEAT_METADATA"
    assert payload["summary"]["operator_restart_reason"] == "stale_heartbeat_metadata"
    assert payload["next_actions"][0]["gate_id"] == "daily_roll_runtime_identity_current"

    report = render_readiness_report(payload)
    assert "artifact_liveness_status" in report
    assert "STALE_HEARTBEAT_METADATA" in report


def test_live_readiness_snapshot_passes_only_when_all_hard_gates_pass(tmp_path):
    live_readiness_path = write_json(
        tmp_path / "live_readiness.json",
        {
            "account_platform_verified": True,
            "wallet_ready": True,
            "allowance_ready": True,
            "heartbeat_ready": True,
            "user_websocket_ready": True,
            "cancel_all_ready": True,
        },
    )
    platform_path = write_json(tmp_path / "platform.json", platform_verification())

    payload = build_readiness_snapshot(
        status_payload=status_payload(),
        paper_payload=paper_payload(),
        preflight_payload=preflight_payload(),
        live_readiness_path=live_readiness_path,
        platform_verification_path=platform_path,
        now="2026-06-26T17:00:00+00:00",
    )

    assert payload["status"] == "PASS"
    assert payload["live_capital_permission"] is False
    assert payload["requires_explicit_operator_approval"] is True
    assert payload["blockers"] == []
    assert payload["next_actions"] == []
    gate_by_id = {gate["id"]: gate for gate in payload["gates"]}
    assert gate_by_id["latest_preflight_passes"]["detail"] == "latest selected run preflight is PASS for all markets"
    runtime_gate = gate_by_id["daily_roll_runtime_identity_current"]
    assert runtime_gate["detail"] == "running daily-roll code identity matches the current source tree"


def test_readiness_snapshot_can_load_one_shot_run_folder_from_status_payload(tmp_path):
    run_folder = tmp_path / "mm_runs" / "2026-06-27" / "run-1"
    write_json(
        run_folder / "run_summary.json",
        {
            "target_date": "2026-06-27",
            "preflight_status": "WARN",
            "preflight_diagnostics": {
                "stale_market_count": 0,
                "blocked_market_count": 1,
                "top_failing_gates": [{"gate": "clob_tokens", "market_count": 1}],
            },
            "quote_permission_rows": 0,
            "live_trade_permission_rows": 0,
        },
    )
    write_json(run_folder / "preflight.json", preflight_payload(status="WARN", failing_gate="clob_tokens"))
    write_json(
        run_folder / "live_forward_gate.json",
        {"status": "BLOCK", "counts_toward_live_forward_gate": False},
    )

    payload = build_readiness_snapshot(
        status_payload={
            "status": "shadow_probe",
            "target_date": "2026-06-27",
            "root_cause_class": "policy_no_edge",
            "run_folder": str(run_folder),
            "current_counts_toward_live_forward_gate": False,
            "live_forward_gate_status": "BLOCK",
            "operator_report": {
                "supervisor_state": "NOT_APPLICABLE",
                "supervisor_action": "one_shot_shadow",
                "supervisor_runtime_identity_matches_current": False,
            },
        },
        paper_payload=paper_payload(target_date="2026-06-27", quote_permission_rows=0),
        live_readiness_path=None,
        platform_verification_path=None,
        now="2026-06-27T04:15:00+00:00",
    )

    assert payload["target_date"] == "2026-06-27"
    assert payload["inputs"]["latest_run_folder"].endswith("run-1")
    assert payload["summary"]["preflight_status"] == "WARN"
    assert payload["summary"]["preflight_blocked_market_count"] == 1
    assert payload["summary"]["live_forward_gate_status"] == "BLOCK"
    assert payload["summary"]["runtime_root_cause_class"] is None
    blockers = {gate["id"] for gate in payload["blockers"]}
    gate_by_id = {gate["id"]: gate for gate in payload["gates"]}
    assert "latest_preflight_passes" in blockers
    assert "clob_capture_and_reward_metadata_fresh" in blockers
    assert "daily_roll_runtime_identity_current" not in blockers
    assert gate_by_id["daily_roll_runtime_identity_current"]["ok"] is True
    assert "not applicable for this one-shot run-summary status" in gate_by_id["daily_roll_runtime_identity_current"]["detail"]
    assert gate_by_id["daily_roll_runtime_identity_current"]["evidence"]["run_summary_root_cause_class"] == "policy_no_edge"


def test_find_latest_paper_score_prefers_newest_mm_paper_json(tmp_path):
    old = write_json(tmp_path / "mm_paper_report.json", {"summary": {"quote_permission_rows": 0}})
    new = write_json(tmp_path / "mm_paper_new.json", {"summary": {"quote_permission_rows": 1}})
    old.touch()
    new.touch()

    assert find_latest_paper_score(tmp_path) == new


def test_find_latest_paper_score_prefers_matching_target_date(tmp_path):
    older_matching = write_json(tmp_path / "mm_paper_20260626.json", paper_payload(target_date="2026-06-26"))
    newer_other_day = write_json(tmp_path / "mm_paper_20260627.json", paper_payload(target_date="2026-06-27"))
    os.utime(older_matching, (100, 100))
    os.utime(newer_other_day, (200, 200))

    assert find_latest_paper_score(tmp_path, target_date="2026-06-26") == older_matching
    assert find_latest_paper_score(tmp_path) == newer_other_day


def test_readiness_snapshot_selects_matching_paper_score_by_default(tmp_path):
    matching = write_json(
        tmp_path / "mm_paper_20260626.json",
        paper_payload(target_date="2026-06-26", quote_permission_rows=3),
    )
    newer_other_day = write_json(
        tmp_path / "mm_paper_20260627.json",
        paper_payload(target_date="2026-06-27", quote_permission_rows=99),
    )
    os.utime(matching, (100, 100))
    os.utime(newer_other_day, (200, 200))

    payload = build_readiness_snapshot(
        status_payload=status_payload(),
        preflight_payload=preflight_payload(),
        backtest_root=tmp_path,
        live_readiness_path=None,
        platform_verification_path=None,
        now="2026-06-26T17:00:00+00:00",
    )

    gate_by_id = {gate["id"]: gate for gate in payload["gates"]}
    assert gate_by_id["readiness_inputs_target_date_aligned"]["ok"] is True
    assert payload["inputs"]["paper_score_path"].endswith("mm_paper_20260626.json")
    assert payload["summary"]["paper_score_quote_permission_rows"] == 3
    assert payload["summary"]["paper_score_gate_status"] == "OPEN"
    assert payload["summary"]["paper_score_gate_scope"] == "paper_day_collection_and_exchange_economics_not_live_capital"
    assert payload["summary"]["paper_score_live_capital_gate_status"] == "NOT_EVALUATED_BY_MM_PAPER"


def test_render_readiness_report_lists_blockers():
    payload = build_readiness_snapshot(
        status_payload=status_payload(),
        paper_payload=paper_payload(fill_evidence_completeness_status="BLOCK", fill_evidence_promotion_grade=False),
        latest_run_summary={
            "preflight_remediation": {
                "status": "BLOCK",
                "root_cause_counts": {"observation_trigger_stale_code_markets": 1},
                "owner_counts": {"observation-trigger supervisor": 1},
            }
        },
        preflight_payload=preflight_payload(),
        live_readiness_path=None,
        platform_verification_path=None,
        now="2026-06-26T17:00:00+00:00",
    )

    report = render_readiness_report(payload)

    assert "# Market-Making Live Readiness" in report
    assert "| `paper_score_quote_permission_rows` |" in report
    assert "| `paper_score_gate_status` |" in report
    assert "| `paper_score_gate_scope` |" in report
    assert "| `paper_score_live_capital_gate_status` |" in report
    assert "NOT_EVALUATED_BY_MM_PAPER" in report
    assert "| `paper_quote_permission_market_counts` |" in report
    assert "| `paper_top_quote_permission_cells` |" in report
    assert "| `paper_quote_blocker_reason_counts` |" in report
    assert "| `latest_tick_quote_permission_rows` |" in report
    assert "| `latest_tick_reason_counts` |" in report
    assert "| `known_edge_map_record_count` |" in report
    assert "| `known_edge_map_diagnostic_only` |" in report
    assert "| `paper_score_freshness_status` |" in report
    assert "| `live_forward_day_count` |" in report
    assert "| `fill_evidence_blockers` |" in report
    assert "| `fill_evidence_effective_promotion_grade` |" in report
    assert "| `fill_evidence_vacuous` |" in report
    assert "| `fill_evidence_quote_legs` |" in report
    assert "| `missing_size_trade_rows` |" in report
    assert "| `counterfactual_reward_usdc` |" in report
    assert "| `preflight_status` |" in report
    assert "| `preflight_remediation_root_cause_counts` |" in report
    assert "| `observation_trigger_runtime_root_cause_counts` |" in report
    assert "| `snapshot_model_source_failing_gate_counts` |" in report
    assert "| `snapshot_model_source_failing_markets` |" in report
    assert "| `model_freshness_failed_market_count` |" in report
    assert "| `model_freshness_failed_markets` |" in report
    assert "| `source_status_degradation_failed_market_count` |" in report
    assert "| `source_status_degradation_failed_markets` |" in report
    assert "| `source_status_blocker_status` |" in report
    assert "| `source_status_settlement_auth_failures_per_market` |" in report
    assert "| `source_status_settlement_auth_failure_market_count` |" in report
    assert "| `source_status_repair_command` |" in report
    assert "## Next Actions" in report
    assert "| `40` | `fills_pnl` | `fill_evidence_complete` |" in report
    assert "`fill_evidence_complete`" in report
    assert "Status: `BLOCK`" in report
