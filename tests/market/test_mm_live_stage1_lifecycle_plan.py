from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests.live_candidate_fixture import build_current_gamma_event_payload
from weather.market import mm_live_stage0_scope as stage0_scope
from weather.market import mm_live_stage1_lifecycle_plan as lifecycle_plan
from weather.market.market_config import config_for_date


NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
TARGET_DATE = "2026-08-31"
CONDITION_ID = "0x" + "1" * 64
TOKEN_ID = "101"
ALTERNATE_TOKEN_ID = "102"


def _write_json(path, payload):
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _event_payload(*, generated_at=NOW):
    market_id = "toronto"
    event_slug = config_for_date(TARGET_DATE, market_id).event_slug
    location_spec = next(
        spec for spec in stage0_scope.BUILTIN_SPECS if spec.id == market_id
    )
    return {
        "schema_version": stage0_scope.EVENT_METADATA_SCHEMA_VERSION,
        "status": "generated_snapshot",
        "owner": "weather.operations.location_config_refresh",
        "generated_at_utc": generated_at.isoformat(),
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
                "source_event_dates": [TARGET_DATE],
                "active_events": [
                    {
                        "event_id": "event-1",
                        "event_date": TARGET_DATE,
                        "event_slug": event_slug,
                        "event_url": f"https://polymarket.com/event/{event_slug}",
                        "title": "Highest temperature test event",
                        "end_date": f"{TARGET_DATE}T23:00:00Z",
                        "resolution_source_url": "https://example.invalid/weather",
                        "market_count": 1,
                        "markets": [
                            {
                                "polymarket_market_id": "market-1",
                                "condition_id": CONDITION_ID,
                                "range_label": "test-range",
                                "question": "Will the selected range settle true?",
                                "enable_order_book": True,
                                "active": True,
                                "closed": False,
                                "outcomes": [
                                    {
                                        "index": 0,
                                        "name": "Yes",
                                        "token_id": TOKEN_ID,
                                    },
                                    {
                                        "index": 1,
                                        "name": "No",
                                        "token_id": ALTERNATE_TOKEN_ID,
                                    },
                                ],
                                "outcome_tokens": {
                                    "Yes": TOKEN_ID,
                                    "No": ALTERNATE_TOKEN_ID,
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _event_file(tmp_path, *, generated_at=NOW):
    return _write_json(
        tmp_path / "location-market-events.json",
        _event_payload(generated_at=generated_at),
    )


def _gamma_payload():
    return build_current_gamma_event_payload(
        target_date=TARGET_DATE,
        condition_id=CONDITION_ID,
        token_id=TOKEN_ID,
        alternate_token_id=ALTERNATE_TOKEN_ID,
    )


def _book(
    *,
    bids=("0.01",),
    asks=("0.20",),
    minimum="5",
    tick="0.01",
    neg_risk=False,
    token_id=TOKEN_ID,
    condition_id=CONDITION_ID,
):
    return {
        "asset_id": token_id,
        "market": condition_id,
        "min_order_size": minimum,
        "tick_size": tick,
        "neg_risk": neg_risk,
        "bids": [{"price": price, "size": "10"} for price in bids],
        "asks": [{"price": price, "size": "10"} for price in asks],
    }


def _rules(*, tick="0.01", neg_risk=False, fee_rate_bps="0", token_id=TOKEN_ID):
    return {
        "token_id": token_id,
        "tick_size": Decimal(tick),
        "neg_risk": neg_risk,
        "fee_rate_bps": Decimal(fee_rate_bps),
    }


def _select(
    tmp_path,
    *,
    book=None,
    rules=None,
    gamma=None,
    generated_at=NOW,
    now=NOW,
    output_name="lifecycle-plan.json",
):
    event_path = _event_file(tmp_path, generated_at=generated_at)
    plan_path = tmp_path / output_name
    payload = lifecycle_plan.select_stage1_lifecycle_plan(
        event_path,
        TARGET_DATE,
        plan_path,
        expected_condition_id=CONDITION_ID,
        expected_token_id=TOKEN_ID,
        now=now,
        book_reader=lambda _tokens: [book or _book()],
        rule_reader=lambda _token: rules or _rules(),
        gamma_reader=lambda _slug: gamma if gamma is not None else _gamma_payload(),
    )
    return payload, plan_path


def _rehash(payload):
    payload["plan_sha256"] = lifecycle_plan.stage1_lifecycle_plan_sha256(payload)
    return payload


def test_wide_off_center_book_and_zero_fee_pass_without_stage2_gates(tmp_path):
    payload, plan_path = _select(
        tmp_path,
        book=_book(bids=("0.01",), asks=("0.20",)),
        rules=_rules(fee_rate_bps="0"),
    )

    assert payload["status"] == "PASS"
    assert payload["selected"]["best_ask"] == 0.20
    assert payload["selected"]["fee_rate"] == 0
    assert payload["selected"]["fee_rate_bps"] == 0
    assert payload["selected"]["stage1_intent"] == {
        "side": "BUY",
        "price": 0.01,
        "size": 5.0,
        "notional_pusd": 0.05,
        "post_only": True,
    }
    serialized = json.dumps(payload, sort_keys=True)
    for forbidden in (
        '"spread"',
        '"midpoint"',
        '"best_bid_depth"',
        '"best_ask_depth"',
        '"paper_quote_proof"',
        '"maker_rebate_rate"',
        '"expected_net_edge"',
    ):
        assert forbidden not in serialized

    gate = lifecycle_plan.load_stage1_lifecycle_plan_gate(
        plan_path,
        TARGET_DATE,
        expected_condition_id=CONDITION_ID,
        expected_token_id=TOKEN_ID,
        now=NOW,
    )
    assert gate["fee_rate"] == 0
    assert gate["stage1_intent"]["post_only"] is True
    assert lifecycle_plan.load_stage1_lifecycle_discovery_gate(
        plan_path,
        now=NOW,
    )["token_id"] == TOKEN_ID


def test_empty_book_sides_pass_with_no_best_ask(tmp_path):
    payload, plan_path = _select(
        tmp_path,
        book=_book(bids=(), asks=()),
    )

    assert payload["status"] == "PASS"
    assert payload["selected"]["best_ask"] is None
    assert lifecycle_plan.load_stage1_lifecycle_discovery_gate(
        plan_path,
        now=NOW,
    )["best_ask"] is None


@pytest.mark.parametrize("ask", ["0.01", "0.005"])
def test_ask_at_or_below_tick_blocks_nonmarketable_buy(tmp_path, ask):
    payload, _plan_path = _select(
        tmp_path,
        book=_book(asks=(ask,)),
    )

    assert payload["status"] == "BLOCK"
    assert payload["missing"] == ["minimum_tick_buy_nonmarketable"]


def test_minimum_order_above_ten_pusd_blocks(tmp_path):
    payload, _plan_path = _select(
        tmp_path,
        book=_book(minimum="101", tick="0.1", asks=("0.2",)),
        rules=_rules(tick="0.1"),
    )

    assert payload["status"] == "BLOCK"
    assert payload["missing"] == ["minimum_order_notional_within_10_pusd"]


def test_negative_fee_blocks_but_zero_does_not(tmp_path):
    payload, _plan_path = _select(
        tmp_path,
        rules=_rules(fee_rate_bps="-1"),
    )

    assert payload["status"] == "BLOCK"
    assert payload["missing"] == ["finite_nonnegative_current_fee_rate"]


@pytest.mark.parametrize(
    ("book", "rules"),
    [
        (_book(tick="0.01"), _rules(tick="0.005")),
        (_book(neg_risk=False), _rules(neg_risk=True)),
    ],
)
def test_book_rule_tick_or_neg_risk_drift_blocks(tmp_path, book, rules):
    payload, _plan_path = _select(tmp_path, book=book, rules=rules)

    assert payload["status"] == "BLOCK"
    assert payload["missing"] == ["exact_book_rule_tick_and_neg_risk"]


def test_old_staged_metadata_passes_when_current_gamma_matches(tmp_path):
    payload, _plan_path = _select(
        tmp_path,
        generated_at=NOW - timedelta(days=30),
    )

    assert payload["status"] == "PASS"
    assert payload["event_metadata"]["generated_at_utc"] == (
        NOW - timedelta(days=30)
    ).isoformat()


def test_gamma_check_precedes_lifecycle_plan_creation_clock(tmp_path, monkeypatch):
    stage0_ticks = iter(
        [
            NOW - timedelta(seconds=3),
            NOW - timedelta(seconds=2),
            NOW - timedelta(seconds=1),
        ]
    )

    def stepped_stage0_utc_now(override=None):
        return override if override is not None else next(stage0_ticks)

    monkeypatch.setattr(stage0_scope, "utc_now", stepped_stage0_utc_now)
    monkeypatch.setattr(
        lifecycle_plan,
        "utc_now",
        lambda override=None: override if override is not None else NOW,
    )
    payload, plan_path = _select(
        tmp_path,
        generated_at=NOW - timedelta(days=30),
        now=None,
    )

    assert payload["current_gamma"]["checked_at_utc"] == (
        NOW - timedelta(seconds=1)
    ).isoformat()
    assert payload["created_at_utc"] == NOW.isoformat()
    assert lifecycle_plan.load_stage1_lifecycle_discovery_gate(
        plan_path,
        now=NOW,
    )["ok"] is True


@pytest.mark.parametrize(
    "drift",
    [
        "event_closed",
        "event_inactive",
        "market_closed",
        "market_inactive",
        "superseded",
        "condition_mapping",
        "token_mapping",
    ],
)
def test_current_gamma_drift_blocks_lifecycle_generation(tmp_path, drift):
    current = _gamma_payload()
    if drift == "event_closed":
        current["closed"] = True
    elif drift == "event_inactive":
        current["active"] = False
    elif drift == "market_closed":
        current["markets"][0]["closed"] = True
    elif drift == "market_inactive":
        current["markets"][0]["active"] = False
    elif drift == "superseded":
        current["id"] = "replacement-event"
    elif drift == "condition_mapping":
        current["markets"][0]["conditionId"] = "0x" + "3" * 64
    else:
        current["markets"][0]["clobTokenIds"] = json.dumps(
            [TOKEN_ID, "999"]
        )

    with pytest.raises(RuntimeError, match="current Gamma rebind"):
        _select(
            tmp_path,
            gamma=current,
            generated_at=NOW - timedelta(days=30),
        )
    assert not (tmp_path / "lifecycle-plan.json").exists()


def test_wrong_external_stage0_scope_fails_loader(tmp_path):
    _payload, plan_path = _select(tmp_path)

    with pytest.raises(RuntimeError, match="exact_stage0_scope|selection_policy"):
        lifecycle_plan.load_stage1_lifecycle_plan_gate(
            plan_path,
            TARGET_DATE,
            expected_condition_id="0x" + "2" * 64,
            expected_token_id="202",
            now=NOW,
        )


def test_stale_plan_fails_loader(tmp_path):
    _payload, plan_path = _select(tmp_path)

    with pytest.raises(RuntimeError, match="current"):
        lifecycle_plan.load_stage1_lifecycle_discovery_gate(
            plan_path,
            now=NOW + timedelta(seconds=lifecycle_plan.MAX_PLAN_AGE_SECONDS),
        )


def test_tamper_extra_keys_and_legacy_schema_fail_strict_loader(tmp_path):
    payload, _plan_path = _select(tmp_path)

    tampered = json.loads(json.dumps(payload))
    tampered["selected"]["stage1_intent"]["size"] = 4
    tampered_path = _write_json(tmp_path / "tampered.json", tampered)
    with pytest.raises(RuntimeError, match="plan_hash"):
        lifecycle_plan.load_stage1_lifecycle_discovery_gate(
            tampered_path,
            now=NOW,
        )

    rehashed_event_id = json.loads(json.dumps(payload))
    rehashed_event_id["current_gamma"]["event_contracts"][0]["event_id"] = (
        "forged-event"
    )
    rehashed_event_id_path = _write_json(
        tmp_path / "rehashed-event-id.json",
        _rehash(rehashed_event_id),
    )
    with pytest.raises(RuntimeError, match="current_gamma_binding"):
        lifecycle_plan.load_stage1_lifecycle_discovery_gate(
            rehashed_event_id_path,
            now=NOW,
        )

    duplicate_event = json.loads(json.dumps(payload))
    duplicate_event["current_gamma"]["event_contracts"].append(
        json.loads(
            json.dumps(duplicate_event["current_gamma"]["event_contracts"][0])
        )
    )
    duplicate_event_path = _write_json(
        tmp_path / "duplicate-event.json",
        _rehash(duplicate_event),
    )
    with pytest.raises(RuntimeError, match="current_gamma_binding"):
        lifecycle_plan.load_stage1_lifecycle_discovery_gate(
            duplicate_event_path,
            now=NOW,
        )

    gamma_tampered = json.loads(json.dumps(payload))
    gamma_tampered["current_gamma"]["event_contracts"][0][
        "contract_sha256"
    ] = "d" * 64
    gamma_tampered_path = _write_json(
        tmp_path / "gamma-tampered.json",
        gamma_tampered,
    )
    with pytest.raises(RuntimeError, match="plan_hash"):
        lifecycle_plan.load_stage1_lifecycle_discovery_gate(
            gamma_tampered_path,
            now=NOW,
        )

    extra = json.loads(json.dumps(payload))
    extra["unexpected"] = True
    extra_path = _write_json(tmp_path / "extra.json", _rehash(extra))
    with pytest.raises(RuntimeError, match="exact_schema_shape"):
        lifecycle_plan.load_stage1_lifecycle_discovery_gate(
            extra_path,
            now=NOW,
        )

    legacy = json.loads(json.dumps(payload))
    legacy["schema_version"] = "mm_live_candidate_plan_v0.4"
    legacy_path = _write_json(tmp_path / "legacy.json", _rehash(legacy))
    with pytest.raises(RuntimeError, match="schema"):
        lifecycle_plan.load_stage1_lifecycle_discovery_gate(
            legacy_path,
            now=NOW,
        )
