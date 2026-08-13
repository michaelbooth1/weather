import json

import pytest

from weather.market import exchange_economics


NOW = "2026-06-24T12:00:00+00:00"
TARGET_DATE = "2026-06-24"


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _snapshot(**overrides):
    payload = exchange_economics.build_snapshot_payload(
        target_date=overrides.pop("target_date", TARGET_DATE),
        verified_at_utc=overrides.pop("verified_at_utc", NOW),
        **overrides,
    )
    payload["snapshot_id"] = exchange_economics.snapshot_id(payload)
    payload["exchange_economics_hash"] = exchange_economics.snapshot_hash(payload)
    return payload


def test_exchange_economics_snapshot_passes_when_current(tmp_path):
    path = _write(tmp_path / "exchange.json", _snapshot())

    gate = exchange_economics.load_exchange_economics_gate(path, TARGET_DATE, now=NOW)

    assert gate["status"] == "PASS"
    assert gate["evidence_basis"] == exchange_economics.CURRENT_EVIDENCE_BASIS
    assert gate["snapshot_id"].startswith("xecon-")
    assert gate["snapshot_hash"]


def test_snapshot_payload_defaults_match_international_rules_and_zero_reward_primary():
    payload = _snapshot()

    assert payload["platform"] == "polymarket_global"
    assert payload["platform_surface"] == "international_clob"
    assert "https://docs.polymarket.com/trading/fees" in payload["source_urls"]
    assert payload["fee_model"]["taker_fee_rate"] == 0.05
    assert payload["fee_model"]["maker_fee_rate"] == 0.0
    assert payload["maker_rebate"]["pool_share"] == 0.25
    assert payload["maker_rebate"]["requires_resting_fill"] is True
    assert payload["maker_rebate"]["requires_actual_reconciliation"] is True
    assert payload["maker_rebate"]["documented_payout_asset"] == "pUSD"
    assert payload["maker_rebate"]["requires_payout_asset_reconciliation"] is True
    assert payload["liquidity_rewards"]["formula"] == "polymarket_global_Q_score_market_specific"
    assert payload["liquidity_rewards"]["primary_pnl_assumption_usdc"] == 0.0
    assert payload["market_rules"]["tick_size"] == 0.01
    assert payload["market_rules"]["min_order_size"] == 5.0
    assert payload["market_rules"]["market_specific_fields_required"] is True
    assert payload["api_order_semantics"]["maker_only_field"] == "postOnly"
    assert payload["markets"][0]["fee_schedule"] == {
        "rate": 0.05,
        "exponent": 1.0,
        "taker_only": True,
        "rebate_rate": 0.25,
    }


def test_stale_snapshot_fails_closed(tmp_path):
    path = _write(
        tmp_path / "exchange.json",
        _snapshot(verified_at_utc="2026-06-22T00:00:00+00:00"),
    )

    gate = exchange_economics.load_exchange_economics_gate(path, TARGET_DATE, now=NOW)

    assert gate["status"] == "BLOCK"
    assert gate["evidence_basis"] == exchange_economics.STALE_EVIDENCE_BASIS
    assert "verified_at_recent" in gate["missing"]


def test_material_drift_requires_rescore_for_fee_reward_tick_and_min_order_changes(tmp_path):
    accepted = _snapshot()
    current = _snapshot(taker_fee_rate=0.06, tick_size=0.005, min_order_size=20.0)
    current["liquidity_rewards"]["formula"] = "polymarket_liquidity_rewards_v2"
    accepted_path = _write(tmp_path / "accepted.json", accepted)
    current_path = _write(tmp_path / "current.json", current)

    report = exchange_economics.build_drift_report(
        current_path,
        accepted_path,
        target_date=TARGET_DATE,
        now=NOW,
    )

    changed_fields = {row["field"] for row in report["material_changes"]}
    assert report["status"] == "BLOCK"
    assert report["rescore_required"] is True
    assert "fee_model" in changed_fields
    assert "liquidity_rewards" in changed_fields
    assert "market_rules.tick_size" in changed_fields
    assert "market_rules.min_order_size" in changed_fields


def test_snapshot_blocks_target_date_mismatch(tmp_path):
    path = _write(tmp_path / "exchange.json", _snapshot(target_date="2026-06-23"))

    gate = exchange_economics.load_exchange_economics_gate(path, TARGET_DATE, now=NOW)

    assert gate["status"] == "BLOCK"
    assert "target_date_matches" in gate["missing"]


def test_snapshot_verified_today_covers_earlier_targets(tmp_path):
    # 2026-07-11: MM (active day D) was blocked against a proof stamped for
    # the settled-analysis target D-1, every day, by construction. A proof
    # taken on date X covers targets on or before X: older-than-target proofs
    # still block (test above) and rules effective after the target are
    # rejected by effective_date_not_after_target.
    payload = _snapshot(target_date="2026-06-24")
    payload["effective_date"] = "2026-04-03"
    payload["snapshot_id"] = exchange_economics.snapshot_id(payload)
    payload["exchange_economics_hash"] = exchange_economics.snapshot_hash(payload)
    path = _write(tmp_path / "exchange.json", payload)

    gate = exchange_economics.load_exchange_economics_gate(path, "2026-06-23", now=NOW)

    assert gate["status"] == "PASS"
    assert gate["checks"]["target_date_matches"] is True
    assert gate["checks"]["effective_date_not_after_target"] is True


def test_manual_template_cannot_masquerade_as_fresh_runtime_proof():
    template = exchange_economics.load_snapshot_template()

    payload = exchange_economics.prepare_snapshot_from_template(
        template,
        target_date=TARGET_DATE,
        now=NOW,
    )
    gate = exchange_economics._check_snapshot_payload(
        payload,
        target_date=TARGET_DATE,
        now=NOW,
    )

    assert gate["status"] == "BLOCK"
    assert gate["evidence_basis"] == exchange_economics.STALE_EVIDENCE_BASIS
    assert "global_live_api_content_bound" in gate["missing"]
    assert "global_markets_recorded" in gate["missing"]


def test_publish_snapshot_from_template_validates_before_overwrite(tmp_path):
    template = exchange_economics.load_snapshot_template()
    template_path = _write(tmp_path / "template.json", template)
    snapshot_path = tmp_path / "exchange.json"
    snapshot_path.write_text('{"keep": true}', encoding="utf-8")

    with pytest.raises(ValueError, match="global_live_api_content_bound"):
        exchange_economics.publish_snapshot_from_template(
            template_path=template_path,
            snapshot_path=snapshot_path,
            target_date=TARGET_DATE,
            now=NOW,
        )

    assert json.loads(snapshot_path.read_text(encoding="utf-8")) == {"keep": True}


def test_publish_accept_and_later_material_drift_round_trip(tmp_path):
    snapshot_path = tmp_path / "exchange.json"
    accepted_path = tmp_path / "accepted.json"
    drift_path = tmp_path / "drift.json"

    published_payload = _snapshot()
    _write(snapshot_path, published_payload)
    accepted = exchange_economics.accept_snapshot_baseline(
        snapshot_path=snapshot_path,
        accepted_snapshot_path=accepted_path,
        drift_report_path=drift_path,
        target_date=TARGET_DATE,
        now=NOW,
    )

    assert accepted["status"] == "PASS"
    assert accepted["drift"]["accepted_snapshot_present"] is True
    assert accepted["drift"]["rescore_required"] is False

    current = json.loads(snapshot_path.read_text(encoding="utf-8"))
    current["fee_model"]["taker_fee_rate"] = 0.06
    current["markets"][0]["fee_schedule"]["rate"] = 0.06
    current["exchange_economics_hash"] = exchange_economics.snapshot_hash(current)
    current["snapshot_id"] = "xecon-" + current["exchange_economics_hash"][:16]
    snapshot_path.write_text(json.dumps(current), encoding="utf-8")

    report = exchange_economics.build_drift_report(
        snapshot_path,
        accepted_path,
        target_date=TARGET_DATE,
        now=NOW,
    )

    assert report["status"] == "BLOCK"
    assert report["rescore_required"] is True
    assert {row["field"] for row in report["material_changes"]} == {
        "fee_model",
        "market_fee_rule_profiles",
    }


def test_daily_condition_identity_rotation_is_not_economics_rule_drift():
    accepted = _snapshot(
        target_date="2026-06-24",
        condition_id="0x" + "1" * 64,
        token_ids=["101", "102"],
    )
    current = _snapshot(
        target_date="2026-06-25",
        verified_at_utc="2026-06-25T12:00:00+00:00",
        condition_id="0x" + "2" * 64,
        token_ids=["201", "202"],
    )

    assert exchange_economics.compare_snapshots(current, accepted) == []


def test_snapshot_fails_closed_on_platform_mismatch(tmp_path):
    path = _write(tmp_path / "exchange.json", _snapshot(platform="polymarket_us"))

    gate = exchange_economics.load_exchange_economics_gate(path, TARGET_DATE, now=NOW)

    assert gate["status"] == "BLOCK"
    assert "platform_matches" in gate["missing"]


def test_snapshot_fails_closed_when_content_proof_is_tampered(tmp_path):
    payload = _snapshot()
    payload["source_verification"]["responses"][0]["response_sha256"] = "c" * 64
    path = _write(tmp_path / "exchange.json", payload)

    gate = exchange_economics.load_exchange_economics_gate(path, TARGET_DATE, now=NOW)

    assert gate["status"] == "BLOCK"
    assert "source_hash_matches_content" in gate["missing"]


def test_snapshot_fails_closed_on_unsupported_weather_fee_curve():
    payload = _snapshot()
    payload["markets"][0]["fee_schedule"]["exponent"] = 2.0

    gate = exchange_economics._check_snapshot_payload(
        payload,
        target_date=TARGET_DATE,
        now=NOW,
    )

    assert gate["status"] == "BLOCK"
    assert "global_market_economics_complete" in gate["missing"]


def test_collect_global_snapshot_binds_gamma_identity_fee_schedule_and_current_rewards(
    tmp_path,
    monkeypatch,
):
    condition_id = "0x" + "2" * 64
    event_slug = "highest-temperature-in-toronto-on-june-24-2026"
    event_metadata_path = _write(tmp_path / "events.json", {"locations": []})
    selected = [{
        "location_id": "toronto",
        "event_slug": event_slug,
        "event_date": TARGET_DATE,
        "registry_markets": [{
            "condition_id": condition_id,
            "polymarket_market_id": "77",
            "question": "Will Toronto be 25 C?",
            "outcomes": [
                {"name": "Yes", "token_id": "201"},
                {"name": "No", "token_id": "202"},
            ],
        }],
    }]
    monkeypatch.setattr(
        exchange_economics,
        "_event_rows_for_global_snapshot",
        lambda _payload, _target: (selected, []),
    )

    def fake_fetch(url, *, timeout_seconds):
        del timeout_seconds
        if "/events/slug/" in url:
            return {
                "id": "9",
                "slug": event_slug,
                "markets": [{
                    "id": "77",
                    "conditionId": condition_id,
                    "question": "Will Toronto be 25 C?",
                    "clobTokenIds": '["201", "202"]',
                    "feesEnabled": True,
                    "feeSchedule": {
                        "rate": 0.05,
                        "exponent": 1,
                        "takerOnly": True,
                        "rebateRate": 0.25,
                    },
                    "orderMinSize": 5,
                    "orderPriceMinTickSize": 0.01,
                    "rewardsMinSize": 20,
                    "rewardsMaxSpread": 4.5,
                }],
            }
        return {
            "data": [{
                "condition_id": condition_id,
                "total_daily_rate": 46,
                "rewards_min_size": 20,
                "rewards_max_spread": 4.5,
                "rewards_config": [{
                    "start_date": TARGET_DATE,
                    "end_date": "2500-12-31",
                    "rate_per_day": 46,
                }],
            }],
            "next_cursor": "LTE=",
        }

    payload = exchange_economics.collect_global_snapshot_payload(
        target_date=TARGET_DATE,
        event_metadata_path=event_metadata_path,
        now=NOW,
        fetch_json=fake_fetch,
    )
    gate = exchange_economics._check_snapshot_payload(
        payload,
        target_date=TARGET_DATE,
        now=NOW,
    )

    assert gate["status"] == "PASS"
    assert payload["platform"] == "polymarket_global"
    assert payload["markets"][0]["condition_id"] == condition_id
    assert payload["markets"][0]["token_ids"] == ["201", "202"]
    assert payload["markets"][0]["fee_schedule"]["rebate_rate"] == 0.25
    assert payload["markets"][0]["liquidity_rewards"]["current_daily_rate_usdc"] == 46
    assert payload["liquidity_rewards"]["primary_pnl_assumption_usdc"] == 0.0
    assert payload["source_verification"]["responses"]


def test_paper_legs_bind_to_exact_condition_token_economics_and_missing_tokens_block():
    payload = _snapshot(token_ids=["201", "202"])
    gate = exchange_economics._check_snapshot_payload(
        payload,
        target_date=TARGET_DATE,
        now=NOW,
    )
    legs = [
        {"clob_token_id": "201"},
        {"clob_token_id": "missing"},
    ]

    coverage = exchange_economics.bind_legs_to_market_economics(
        legs,
        payload,
        gate=gate,
    )
    covered_gate = exchange_economics.gate_with_leg_coverage(gate, coverage)

    assert legs[0]["exchange_economics_bound"] is True
    assert legs[0]["maker_rebate_fee_rate"] == 0.05
    assert legs[0]["maker_rebate_pool_share"] == 0.25
    assert legs[1]["exchange_economics_bound"] is False
    assert legs[1]["maker_rebate_fee_rate"] == 0.0
    assert coverage["missing_leg_count"] == 1
    assert covered_gate["status"] == "BLOCK"
    assert "paper_leg_condition_economics_bound" in covered_gate["missing"]


def test_required_invalid_gate_cannot_inject_untrusted_paper_economics():
    payload = _snapshot(token_ids=["201", "202"])
    gate = exchange_economics._check_snapshot_payload(
        payload,
        target_date=TARGET_DATE,
        now="2026-06-27T12:00:00+00:00",
    )
    legs = [{"clob_token_id": "201"}]

    assert gate["status"] == "BLOCK"
    coverage = exchange_economics.bind_legs_to_market_economics(
        legs,
        payload,
        gate=gate,
    )

    assert coverage["source_gate_ok"] is False
    assert coverage["ok"] is False
    assert legs[0]["exchange_economics_bound"] is False
    assert legs[0]["maker_rebate_fee_rate"] == 0.0
    assert legs[0]["maker_rebate_pool_share"] == 0.0
    assert legs[0]["flattening_fee_rate"] == 0.0


def test_string_false_fees_enabled_is_not_valid_evidence():
    payload = _snapshot()
    payload["markets"][0]["fees_enabled"] = "false"

    gate = exchange_economics._check_snapshot_payload(
        payload,
        target_date=TARGET_DATE,
        now=NOW,
    )

    assert gate["status"] == "BLOCK"
    assert "global_market_economics_complete" in gate["missing"]
