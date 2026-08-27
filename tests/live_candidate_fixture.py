"""Canonical strict candidate-plan fixtures shared by live operations tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from weather.market import mm_live_candidate_cli as candidate_cli


def build_live_candidate_payload(
    *,
    now: datetime,
    target_date: str,
    condition_id: str,
    token_id: str,
    market_id: str = "toronto",
    event_slug: str = "toronto-high-temperature-test",
    remaining_seconds: int = 120,
    constrained: bool = True,
    economics_hash: str = "e" * 32,
    accepted_snapshot_file_sha256: str = "a" * 64,
    drift_report_file_sha256: str = "b" * 64,
    paper_run_config_sha256: str = "d" * 64,
    paper_quote_intents_sha256: str = "e" * 64,
) -> dict:
    """Return one complete candidate satisfying the active exact-shape gate."""

    current = now.astimezone(timezone.utc)
    paper_generated = current
    created = current
    checked = current
    paper_expires = paper_generated + timedelta(seconds=remaining_seconds)
    substrate_expires = checked + timedelta(
        seconds=candidate_cli.MAX_SUBSTRATE_PREFLIGHT_AGE_SECONDS
    )
    expires = min(
        created + timedelta(seconds=candidate_cli.MAX_PLAN_AGE_SECONDS),
        paper_expires,
        substrate_expires,
    )
    economics_id = f"xecon-{economics_hash[:16]}"
    acknowledgment = candidate_cli.economics_acceptance_acknowledgment(
        target_date,
        condition_id,
        token_id,
        accepted_snapshot_file_sha256=accepted_snapshot_file_sha256,
        drift_report_file_sha256=drift_report_file_sha256,
    )
    expected_scope = {
        "condition_id": condition_id if constrained else None,
        "token_id": token_id if constrained else None,
    }
    substrate = {
        "schema_version": candidate_cli.SUBSTRATE_PREFLIGHT_SCHEMA_VERSION,
        "receipt_sha256": "0" * 64,
        "checked_at_utc": checked.isoformat(),
        "expires_at_utc": substrate_expires.isoformat(),
        "market_id": market_id,
        "target_date": target_date,
        "event_slug": event_slug,
        "validation_hash": "1" * 64,
        "event_metadata_file_sha256": "2" * 64,
        "event_metadata_validation_file_sha256": "3" * 64,
        "observation_status_file_sha256": "4" * 64,
        "economics_snapshot_file_sha256": "5" * 64,
        "accepted_snapshot_file_sha256": accepted_snapshot_file_sha256,
        "economics_drift_report_file_sha256": drift_report_file_sha256,
        "paper_run_config_file_sha256": paper_run_config_sha256,
        "paper_preflight_file_sha256": "6" * 64,
        "paper_quote_intents_file_sha256": paper_quote_intents_sha256,
        "clob_tokens_file_sha256": "7" * 64,
        "order_books_summary_file_sha256": "8" * 64,
        "source_status_long_file_sha256": "9" * 64,
        "network_access": False,
        "credential_access": False,
        "exchange_contact": False,
        "exchange_mutation": False,
    }
    payload = {
        "schema_version": candidate_cli.SCHEMA_VERSION,
        "status": "PASS",
        "created_at_utc": created.isoformat(),
        "expires_at_utc": expires.isoformat(),
        "target_date": target_date,
        "platform": candidate_cli.PLATFORM,
        "settlement_unit": candidate_cli.SETTLEMENT_UNIT,
        "exchange_economics_snapshot_id": economics_id,
        "exchange_economics_sha256": economics_hash,
        "economics_gate_ok": True,
        "economics_gate_missing": [],
        "economics_acceptance": {
            "accepted_at_utc": current.isoformat(),
            "accepted_snapshot_file_sha256": accepted_snapshot_file_sha256,
            "accepted_snapshot_id": economics_id,
            "accepted_snapshot_sha256": economics_hash,
            "drift_generated_at_utc": current.isoformat(),
            "drift_report_file_sha256": drift_report_file_sha256,
            "drift_status": "PASS",
            "operator_acknowledgment": acknowledgment,
            "operator_acknowledgment_matches_candidate": True,
            "required_operator_acknowledgment": acknowledgment,
            "rescore_required": False,
        },
        "substrate_preflight": substrate,
        "selection_is_trading_authorization": False,
        "secret_values_retained": False,
        "selection_policy": {
            "built_in_locations_only": True,
            "positive_fee_and_rebate_required": True,
            "midpoint_interval": [
                float(candidate_cli.MIN_MIDPOINT),
                float(candidate_cli.MAX_MIDPOINT),
            ],
            "max_spread": float(candidate_cli.MAX_BOOK_SPREAD),
            "minimum_tick_buy_must_be_nonmarketable": True,
            "book_tick_min_size_and_neg_risk_must_be_current": True,
            "plan_max_age_seconds": candidate_cli.MAX_PLAN_AGE_SECONDS,
            "max_single_order_notional_pusd": float(
                candidate_cli.MAX_SINGLE_ORDER_NOTIONAL
            ),
            "successful_current_market_harvest_quote_required": True,
            "expected_bootstrap_scope": expected_scope,
            "ranking": "spread_asc_then_best_level_depth_desc_then_midpoint_distance",
        },
        "paper_quote_evidence": {
            "run_config_sha256": paper_run_config_sha256,
            "quote_intents_sha256": paper_quote_intents_sha256,
            "quote_intents_row_count": 1,
            "market_id": market_id,
            "run_id": "paper-run-1",
        },
        "candidate_count": 1,
        "selected": {
            "location_id": market_id,
            "event_date": target_date,
            "event_slug": event_slug,
            "question": "Will the selected high-temperature range settle true?",
            "condition_id": condition_id,
            "token_id": token_id,
            "outcome_index": 0,
            "best_bid": 0.49,
            "best_ask": 0.50,
            "midpoint": 0.495,
            "spread": 0.01,
            "best_bid_depth": 100.0,
            "best_ask_depth": 100.0,
            "tick_size": 0.01,
            "order_min_size": 5.0,
            "neg_risk": False,
            "fee_rate": 0.05,
            "maker_rebate_rate": 0.25,
            "reward_min_size": 20.0,
            "reward_max_spread_cents": 4.5,
            "current_book_within_reward_spread": True,
            "lifecycle_probe_reward_min_size_met": False,
            "book_sha256": "c" * 64,
            "stage1_intent": {
                "side": "BUY",
                "price": 0.01,
                "size": 5.0,
                "notional_pusd": 0.05,
                "post_only": True,
            },
            "paper_quote_proof": {
                "run_id": "paper-run-1",
                "market_id": market_id,
                "target_date": target_date,
                "condition_id": condition_id,
                "token_id": token_id,
                "range_label": "test-range",
                "exchange_economics_snapshot_id": economics_id,
                "exchange_economics_hash": economics_hash,
                "policy_hash": "paper-policy-hash",
                "generated_at_utc": paper_generated.isoformat(),
                "expires_at_utc": paper_expires.isoformat(),
                "quote_ttl_seconds": remaining_seconds,
                "bid_price": 0.48,
                "bid_size": 5.0,
                "ask_price": 0.51,
                "ask_size": 5.0,
                "quote_risk_pusd": 4.85,
                "quote_permission": True,
                "live_trade_permission": False,
                "two_sided_post_only_intent": True,
                "reward_and_rebate_assumed_zero": True,
                "quote_row_sha256": "f" * 64,
            },
        },
        "alternates": [],
        "missing": [],
    }
    payload["plan_sha256"] = candidate_cli.candidate_plan_sha256(payload)
    return payload
