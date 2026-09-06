"""Canonical strict candidate-plan fixtures shared by live operations tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from weather.market import mm_live_stage0_scope as stage0_scope
from weather.market import mm_live_stage1_lifecycle_plan as lifecycle_plan
from weather.market.market_config import config_for_date


def build_stage0_event_metadata_payload(
    *,
    generated_at: datetime,
    target_date: str,
    condition_id: str,
    token_id: str,
    alternate_token_id: str = "2",
    market_id: str = "toronto",
) -> dict:
    """Return one structurally valid generated International event snapshot."""

    generated = generated_at.astimezone(timezone.utc)
    event_slug = config_for_date(target_date, market_id).event_slug
    location_spec = next(
        spec for spec in stage0_scope.BUILTIN_SPECS if spec.id == market_id
    )
    return {
        "schema_version": stage0_scope.EVENT_METADATA_SCHEMA_VERSION,
        "status": "generated_snapshot",
        "owner": "weather.operations.location_config_refresh",
        "generated_at_utc": generated.isoformat(),
        "source": {
            "category_url": "https://polymarket.com/weather/high-temperature",
            "gamma_events_query": (
                "https://gamma-api.polymarket.com/events?"
                "tag_slug=highest-temperature&active=true&closed=false&"
                "limit=100&offset={offset}"
            ),
            "tag_slug": "highest-temperature",
            "active": True,
            "closed": False,
            "event_count": 1,
            "location_count": 1,
            "api_page_size": 100,
            "api_offsets_fetched": [0],
            "locations_in_api_not_file": [],
            "locations_in_file_not_api": [],
        },
        "locations": [
            {
                "location_id": market_id,
                "event_slug_prefix": location_spec.slug_prefix,
                "series_slug": f"{market_id}-daily-weather",
                "latest_event_slug": event_slug,
                "latest_event_url": f"https://polymarket.com/event/{event_slug}",
                "source_event_count": 1,
                "source_event_dates": [target_date],
                "active_events": [
                    {
                        "event_id": "event-1",
                        "event_date": target_date,
                        "event_slug": event_slug,
                        "event_url": f"https://polymarket.com/event/{event_slug}",
                        "title": "Highest temperature test event",
                        "end_date": f"{target_date}T23:00:00Z",
                        "resolution_source_url": "https://example.invalid/weather",
                        "market_count": 1,
                        "markets": [
                            {
                                "polymarket_market_id": "market-1",
                                "condition_id": condition_id,
                                "range_label": "test-range",
                                "question": "Will the selected range settle true?",
                                "enable_order_book": True,
                                "active": True,
                                "closed": False,
                                "outcomes": [
                                    {
                                        "index": 0,
                                        "name": "Yes",
                                        "token_id": token_id,
                                    },
                                    {
                                        "index": 1,
                                        "name": "No",
                                        "token_id": alternate_token_id,
                                    },
                                ],
                                "outcome_tokens": {
                                    "Yes": token_id,
                                    "No": alternate_token_id,
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    }


def build_current_gamma_event_payload(
    *,
    target_date: str,
    condition_id: str,
    token_id: str,
    alternate_token_id: str = "2",
    market_id: str = "toronto",
    event_id: str = "event-1",
    polymarket_market_id: str = "market-1",
) -> dict:
    """Return a current Gamma response exactly matching the staged fixture."""

    event_slug = config_for_date(target_date, market_id).event_slug
    return {
        "id": event_id,
        "slug": event_slug,
        "active": True,
        "closed": False,
        "markets": [
            {
                "id": polymarket_market_id,
                "conditionId": condition_id,
                "enableOrderBook": True,
                "active": True,
                "closed": False,
                "outcomes": json.dumps(["Yes", "No"]),
                "clobTokenIds": json.dumps(
                    [str(token_id), str(alternate_token_id)]
                ),
            }
        ],
    }


def build_current_gamma_binding(
    *,
    checked_at: datetime,
    target_date: str,
    condition_id: str,
    token_id: str,
    alternate_token_id: str = "2",
    market_id: str = "toronto",
) -> dict:
    """Return strict evidence for the current Gamma fixture contract."""

    payload = build_current_gamma_event_payload(
        target_date=target_date,
        condition_id=condition_id,
        token_id=token_id,
        alternate_token_id=alternate_token_id,
        market_id=market_id,
    )
    event_slug = config_for_date(target_date, market_id).event_slug
    staged_contract = stage0_scope._current_gamma_contract(
        payload,
        expected_slug=event_slug,
    )
    _contract, evidence = (
        stage0_scope.current_gamma_event_contract_evidence(
            payload,
            expected_slug=event_slug,
            staged_contract=staged_contract,
        )
    )
    return {
        "checked_at_utc": checked_at.astimezone(timezone.utc).isoformat(),
        "event_contracts": [evidence],
    }


def build_stage0_scope_payload(
    *,
    now: datetime,
    target_date: str,
    condition_id: str,
    token_id: str,
    event_metadata_file_sha256: str,
    event_metadata_generated_at: datetime | None = None,
    market_id: str = "toronto",
    alternate_token_id: str = "2",
    remaining_seconds: int = stage0_scope.MAX_PLAN_AGE_SECONDS,
    constrained: bool = True,
    best_bid: float | None = 0.30,
    best_ask: float | None = 0.55,
    tick_size: float = 0.01,
    order_min_size: float = 5.0,
    neg_risk: bool = False,
) -> dict:
    """Return one complete Stage 0 scope plan satisfying the strict gate."""

    current = now.astimezone(timezone.utc)
    created = current - timedelta(
        seconds=stage0_scope.MAX_PLAN_AGE_SECONDS - remaining_seconds
    )
    generated = (event_metadata_generated_at or created).astimezone(timezone.utc)
    event_slug = config_for_date(target_date, market_id).event_slug
    expected_scope = {
        "condition_id": condition_id if constrained else None,
        "token_id": token_id if constrained else None,
    }
    selected = {
        "location_id": market_id,
        "event_date": target_date,
        "event_slug": event_slug,
        "question": "Will the selected range settle true?",
        "condition_id": condition_id,
        "token_id": token_id,
        "outcome_index": 0,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "order_min_size": order_min_size,
        "tick_size": tick_size,
        "neg_risk": neg_risk,
        "book_sha256": "c" * 64,
    }
    current_gamma = build_current_gamma_binding(
        checked_at=created,
        target_date=target_date,
        condition_id=condition_id,
        token_id=token_id,
        alternate_token_id=alternate_token_id,
        market_id=market_id,
    )
    staged_contracts = {
        row["event_slug"]: row["contract"]
        for row in current_gamma["event_contracts"]
    }
    payload = {
        "schema_version": stage0_scope.SCHEMA_VERSION,
        "status": "PASS",
        "purpose": stage0_scope.PURPOSE,
        "created_at_utc": created.isoformat(),
        "expires_at_utc": (
            created + timedelta(seconds=stage0_scope.MAX_PLAN_AGE_SECONDS)
        ).isoformat(),
        "target_date": target_date,
        "platform": stage0_scope.PLATFORM,
        "settlement_unit": stage0_scope.SETTLEMENT_UNIT,
        "event_metadata": {
            "schema_version": stage0_scope.EVENT_METADATA_SCHEMA_VERSION,
            "file_sha256": event_metadata_file_sha256,
            "generated_at_utc": generated.isoformat(),
            "event_contracts": staged_contracts,
        },
        "current_gamma": current_gamma,
        "selection_is_trading_authorization": False,
        "secret_values_retained": False,
        "scope_policy": {
            "built_in_locations_only": True,
            "current_condition_token_mapping_required": True,
            "current_book_identity_and_rules_required": True,
            "quote_economics_are_not_stage0_gates": True,
            "ranking_is_nonblocking_diagnostic": True,
            "event_metadata_age_is_nonblocking_telemetry": True,
            "plan_max_age_seconds": stage0_scope.MAX_PLAN_AGE_SECONDS,
            "expected_bootstrap_scope": expected_scope,
            "ranking": (
                "two_sided_uncrossed_then_spread_then_midpoint_distance_"
                "then_identity_without_exclusion"
            ),
        },
        "scope_count": 1,
        "selected": selected,
        "alternates": [],
        "missing": [],
    }
    payload["plan_sha256"] = stage0_scope.stage0_scope_plan_sha256(payload)
    return payload


def build_live_candidate_payload(
    *,
    now: datetime,
    target_date: str,
    condition_id: str,
    token_id: str,
    market_id: str = "toronto",
    alternate_token_id: str = "2",
    event_slug: str | None = None,
    remaining_seconds: int = 120,
    constrained: bool = True,
    event_metadata_file_sha256: str = "2" * 64,
    event_metadata_generated_at: datetime | None = None,
    fee_rate_bps: float = 500.0,
    **_retired_economics,
) -> dict:
    """Return one complete Stage 1 lifecycle plan.

    The function name is retained for existing operations-test call sites that
    exercise compatibility ``candidate_plan`` paths and receipt fields.
    """

    current = now.astimezone(timezone.utc)
    remaining = max(0, min(int(remaining_seconds), lifecycle_plan.MAX_PLAN_AGE_SECONDS))
    created = current - timedelta(
        seconds=lifecycle_plan.MAX_PLAN_AGE_SECONDS - remaining
    )
    expires = created + timedelta(seconds=lifecycle_plan.MAX_PLAN_AGE_SECONDS)
    event_slug = event_slug or config_for_date(target_date, market_id).event_slug
    expected_scope = {
        "condition_id": condition_id if constrained else None,
        "token_id": token_id if constrained else None,
    }
    fee_rate = float(fee_rate_bps) / 10000
    current_gamma = build_current_gamma_binding(
        checked_at=created,
        target_date=target_date,
        condition_id=condition_id,
        token_id=token_id,
        alternate_token_id=alternate_token_id,
        market_id=market_id,
    )
    staged_contracts = {
        row["event_slug"]: row["contract"]
        for row in current_gamma["event_contracts"]
    }
    payload = {
        "schema_version": lifecycle_plan.SCHEMA_VERSION,
        "status": "PASS",
        "purpose": lifecycle_plan.PURPOSE,
        "created_at_utc": created.isoformat(),
        "expires_at_utc": expires.isoformat(),
        "target_date": target_date,
        "platform": lifecycle_plan.PLATFORM,
        "settlement_unit": lifecycle_plan.SETTLEMENT_UNIT,
        "event_metadata": {
            "schema_version": stage0_scope.EVENT_METADATA_SCHEMA_VERSION,
            "file_sha256": event_metadata_file_sha256,
            "generated_at_utc": (
                event_metadata_generated_at or created
            ).astimezone(timezone.utc).isoformat(),
            "event_contracts": staged_contracts,
        },
        "current_gamma": current_gamma,
        "selection_is_trading_authorization": False,
        "secret_values_retained": False,
        "lifecycle_policy": {
            "exact_stage0_scope_required": True,
            "current_condition_token_mapping_required": True,
            "current_book_and_official_rules_required": True,
            "fee_rate_may_be_zero": True,
            "minimum_tick_buy_must_be_nonmarketable": True,
            "post_only_required": True,
            "max_single_order_notional_pusd": float(
                lifecycle_plan.MAX_SINGLE_ORDER_NOTIONAL_PUSD
            ),
            "stage2_quote_economics_are_not_stage1_gates": True,
            "plan_max_age_seconds": lifecycle_plan.MAX_PLAN_AGE_SECONDS,
            "expected_stage0_scope": expected_scope,
        },
        "selected": {
            "location_id": market_id,
            "event_date": target_date,
            "event_slug": event_slug,
            "question": "Will the selected high-temperature range settle true?",
            "condition_id": condition_id,
            "token_id": token_id,
            "outcome_index": 0,
            "best_ask": 0.50,
            "tick_size": 0.01,
            "order_min_size": 5.0,
            "neg_risk": False,
            "fee_rate": fee_rate,
            "fee_rate_bps": float(fee_rate_bps),
            "book_sha256": "c" * 64,
            "stage1_intent": {
                "side": "BUY",
                "price": 0.01,
                "size": 5.0,
                "notional_pusd": 0.05,
                "post_only": True,
            },
        },
        "missing": [],
    }
    payload["plan_sha256"] = lifecycle_plan.stage1_lifecycle_plan_sha256(payload)
    return payload
