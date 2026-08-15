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
    assert payload["fee_model"]["fee_precision_decimals"] == 5
    assert payload["fee_model"]["minimum_nonzero_fee_usdc"] == 0.00001
    assert payload["fee_model"]["subminimum_fee_rounds_to_zero"] is True
    assert payload["maker_rebate"]["pool_share"] == 0.25
    assert payload["maker_rebate"]["requires_resting_fill"] is True
    assert payload["maker_rebate"]["requires_actual_reconciliation"] is True
    assert payload["maker_rebate"]["documented_payout_asset"] == "pUSD"
    assert payload["maker_rebate"]["program_documented_payout_asset"] == "pUSD"
    assert payload["maker_rebate"]["reconciliation_api_amount_field"] == "rebated_fees_usdc"
    assert payload["maker_rebate"]["reconciliation_api_documented_amount_unit"] == "USDC"
    assert payload["maker_rebate"]["documentation_asset_terms_conflict"] is True
    assert payload["maker_rebate"]["actual_payout_asset_status"] == "wallet_reconciliation_required"
    assert (
        payload["maker_rebate"]["documented_payout_asset_address"]
        == exchange_economics.PUSD_COLLATERAL_PROXY_ADDRESS
    )
    assert (
        payload["maker_rebate"]["payout_asset_address_source"]
        == exchange_economics.PUSD_CONTRACTS_URL
    )
    assert payload["maker_rebate"]["requires_returned_asset_address_match"] is True
    assert payload["maker_rebate"]["minimum_accrued_payout_pusd"] == 1.0
    assert payload["maker_rebate"]["payout_cadence"] == "daily"
    assert payload["maker_rebate"]["calculation_scope"] == "per_market"
    assert payload["maker_rebate"]["requires_minimum_payout_reconciliation"] is True
    assert payload["maker_rebate"]["requires_payout_asset_reconciliation"] is True
    assert payload["maker_rebate"]["actual_reconciliation_endpoint_requires_auth"] is False
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


@pytest.mark.parametrize(
    ("section", "field", "value", "missing_check"),
    [
        ("fee_model", "fee_precision_decimals", 4, "global_fee_precision_recorded"),
        (
            "maker_rebate",
            "minimum_accrued_payout_pusd",
            0.0,
            "global_rebate_minimum_payout_recorded",
        ),
    ],
)
def test_snapshot_blocks_precision_or_minimum_payout_semantics_drift(
    tmp_path,
    section,
    field,
    value,
    missing_check,
):
    payload = _snapshot()
    payload[section][field] = value
    payload["snapshot_id"] = exchange_economics.snapshot_id(payload)
    payload["exchange_economics_hash"] = exchange_economics.snapshot_hash(payload)
    path = _write(tmp_path / "exchange.json", payload)

    gate = exchange_economics.load_exchange_economics_gate(path, TARGET_DATE, now=NOW)

    assert gate["status"] == "BLOCK"
    assert missing_check in gate["missing"]


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
    with pytest.raises(
        ValueError,
        match="explicit payout-asset conflict acknowledgement",
    ):
        exchange_economics.accept_snapshot_baseline(
            snapshot_path=snapshot_path,
            accepted_snapshot_path=accepted_path,
            drift_report_path=drift_path,
            target_date=TARGET_DATE,
            now=NOW,
        )
    assert not accepted_path.exists()

    accepted = exchange_economics.accept_snapshot_baseline(
        snapshot_path=snapshot_path,
        accepted_snapshot_path=accepted_path,
        drift_report_path=drift_path,
        target_date=TARGET_DATE,
        now=NOW,
        acknowledge_payout_asset_conflict=True,
    )

    assert accepted["status"] == "PASS"
    assert accepted["drift"]["accepted_snapshot_present"] is True
    assert accepted["drift"]["rescore_required"] is False
    accepted_payload = json.loads(accepted_path.read_text(encoding="utf-8"))
    assert accepted_payload["accepted_gate"][
        "payout_asset_conflict_acknowledged"
    ] is True

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


def test_snapshot_fails_closed_when_rebate_is_zero_or_endpoint_drifts():
    zero_rebate = _snapshot(maker_rebate_pool_share=0.0)
    zero_gate = exchange_economics._check_snapshot_payload(
        zero_rebate,
        target_date=TARGET_DATE,
        now=NOW,
    )
    assert zero_gate["status"] == "BLOCK"
    assert "maker_rebate_rate_recorded" in zero_gate["missing"]
    assert "global_market_economics_complete" in zero_gate["missing"]

    wrong_endpoint = _snapshot()
    wrong_endpoint["maker_rebate"]["actual_reconciliation_endpoint"] = (
        "https://example.invalid/rebates"
    )
    wrong_gate = exchange_economics._check_snapshot_payload(
        wrong_endpoint,
        target_date=TARGET_DATE,
        now=NOW,
    )
    assert wrong_gate["status"] == "BLOCK"
    assert "global_rebate_payout_asset_reconciliation_required" in wrong_gate["missing"]

    hidden_conflict = _snapshot()
    hidden_conflict["maker_rebate"]["documentation_asset_terms_conflict"] = False
    hidden_conflict_gate = exchange_economics._check_snapshot_payload(
        hidden_conflict,
        target_date=TARGET_DATE,
        now=NOW,
    )
    assert hidden_conflict_gate["status"] == "BLOCK"
    assert (
        "global_rebate_payout_asset_reconciliation_required"
        in hidden_conflict_gate["missing"]
    )

    wrong_asset = _snapshot()
    wrong_asset["maker_rebate"]["documented_payout_asset_address"] = (
        "0x" + "d" * 40
    )
    wrong_asset_gate = exchange_economics._check_snapshot_payload(
        wrong_asset,
        target_date=TARGET_DATE,
        now=NOW,
    )
    assert wrong_asset_gate["status"] == "BLOCK"
    assert (
        "global_rebate_payout_asset_reconciliation_required"
        in wrong_asset_gate["missing"]
    )


def test_snapshot_fails_closed_when_rule_document_semantics_are_not_verified():
    payload = _snapshot()
    payload["source_verification"]["rule_documents"][0]["semantic_checks"] = {
        "fee_formula": False,
    }

    gate = exchange_economics._check_snapshot_payload(
        payload,
        target_date=TARGET_DATE,
        now=NOW,
    )

    assert gate["status"] == "BLOCK"
    assert "global_rule_document_semantics_verified" in gate["missing"]


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

    def fake_fetch_text(url, *, timeout_seconds):
        del timeout_seconds
        documents = {
            "https://docs.polymarket.com/trading/fees.md": """
                fee = C × feeRate × p × (1 - p)
                | Weather | 0.05 | 0 | 25% |
                Fees are rounded to 5 decimal places. The smallest fee charged
                is 0.00001 USDC. Anything smaller rounds to zero.
            """,
            "https://docs.polymarket.com/programs/maker-rebates.md": """
                Paid daily in pUSD. A minimum accrued rebate of 1 pUSD applies.
                | Weather | 25% | Fee-curve weighted |
                fee_equivalent = C × feeRate × p × (1 - p)
                Totals are calculated per market.
            """,
            "https://docs.polymarket.com/programs/liquidity-rewards.md": """
                By posting resting limit orders, makers qualify. Rewards are
                distributed daily at midnight UTC. Each market has a minimum
                qualifying order size, max spread, and min size cutoff.
                Q<sub>n</sub> scoring includes a single-sided adjustment.
            """,
            "https://docs.polymarket.com/api-reference/rewards/get-current-active-rewards-configurations.md": """
                GET /rewards/markets/current condition_id rewards_max_spread
                rewards_min_size total_daily_rate
            """,
            "https://docs.polymarket.com/api-reference/rebates/get-current-rebated-fees-for-a-maker.md": """
                GET /rebates/current. This endpoint does not require authentication.
                maker_address Date in YYYY-MM-DD format condition_id
                asset_address maker_address rebated_fees_usdc
                Each entry includes the USDC amount rebated.
            """,
            "https://docs.polymarket.com/resources/contracts.md": """
                All contracts are deployed on Polygon mainnet (Chain ID: 137).
                pUSD - CollateralToken (proxy)
                0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB
            """,
        }
        return documents[url]

    payload = exchange_economics.collect_global_snapshot_payload(
        target_date=TARGET_DATE,
        event_metadata_path=event_metadata_path,
        now=NOW,
        fetch_json=fake_fetch,
        fetch_text=fake_fetch_text,
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
    assert len(payload["source_verification"]["rule_documents"]) == len(
        exchange_economics.GLOBAL_SOURCE_URLS
    )
    assert all(
        all(row["semantic_checks"].values())
        for row in payload["source_verification"]["rule_documents"]
    )


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
    assert legs[0]["maker_rebate_minimum_accrued_payout_pusd"] == 1.0
    assert legs[1]["exchange_economics_bound"] is False
    assert legs[1]["maker_rebate_fee_rate"] == 0.0
    assert coverage["missing_leg_count"] == 1
    assert covered_gate["status"] == "BLOCK"
    assert "paper_leg_condition_economics_bound" in covered_gate["missing"]


def test_run_capture_is_immutable_and_leg_binding_uses_its_exact_file(tmp_path):
    source = _write(tmp_path / "current.json", _snapshot(token_ids=["201", "202"]))
    gate = exchange_economics.load_exchange_economics_gate(
        source,
        TARGET_DATE,
        now=NOW,
    )
    run_folder = tmp_path / "runs" / TARGET_DATE / "run-1"
    receipt = exchange_economics.capture_run_snapshot(source, run_folder, gate)
    exchange_economics.write_json(
        run_folder / "run_config.json",
        {
            "created_at_utc": NOW,
            "exchange_economics_capture": receipt,
        },
    )
    leg = {
        "run_folder": str(run_folder),
        "target_date": TARGET_DATE,
        "generated_at_utc": NOW,
        "clob_token_id": "201",
        "exchange_economics_snapshot_id": gate["snapshot_id"],
        "exchange_economics_hash": gate["snapshot_hash"],
    }

    coverage = exchange_economics.bind_legs_to_run_snapshots(
        [leg],
        required=True,
    )

    assert receipt["status"] == "CAPTURED"
    assert coverage["ok"] is True
    assert leg["exchange_economics_bound"] is True
    with (run_folder / exchange_economics.RUN_CAPTURE_FILENAME).open(
        "a", encoding="utf-8"
    ) as handle:
        handle.write("\n")
    tampered_leg = {
        **leg,
        "exchange_economics_bound": False,
    }
    tampered = exchange_economics.bind_legs_to_run_snapshots(
        [tampered_leg],
        required=True,
    )
    assert tampered["ok"] is False
    assert tampered_leg["exchange_economics_bound"] is False

    replacement = _snapshot(token_ids=["301", "302"])
    replacement_source = _write(tmp_path / "replacement.json", replacement)
    replacement_gate = exchange_economics.load_exchange_economics_gate(
        replacement_source,
        TARGET_DATE,
        now=NOW,
    )
    with pytest.raises(RuntimeError, match="already binds a different"):
        exchange_economics.capture_run_snapshot(
            replacement_source,
            run_folder,
            replacement_gate,
        )


def test_run_binding_is_bounded_for_interleaved_runs_and_blocks_mixed_identity(tmp_path):
    source = _write(tmp_path / "current.json", _snapshot(token_ids=["201", "202"]))
    gate = exchange_economics.load_exchange_economics_gate(
        source,
        TARGET_DATE,
        now=NOW,
    )
    folders = [tmp_path / "runs" / TARGET_DATE / name for name in ("run-a", "run-b")]
    for folder in folders:
        receipt = exchange_economics.capture_run_snapshot(source, folder, gate)
        exchange_economics.write_json(
            folder / "run_config.json",
            {
                "created_at_utc": NOW,
                "exchange_economics_capture": receipt,
            },
        )

    def leg(folder, *, snapshot_id=None):
        return {
            "run_folder": str(folder),
            "target_date": TARGET_DATE,
            "generated_at_utc": NOW,
            "clob_token_id": "201",
            "exchange_economics_snapshot_id": snapshot_id or gate["snapshot_id"],
            "exchange_economics_hash": gate["snapshot_hash"],
        }

    interleaved = [leg(folders[0]), leg(folders[1]), leg(folders[0])]
    coverage = exchange_economics.bind_legs_to_run_snapshots(
        interleaved,
        required=True,
    )
    receipts = {row["run_folder"]: row for row in coverage["run_receipts"]}

    assert coverage["ok"] is True
    assert coverage["bound_leg_count"] == 3
    assert receipts[str(folders[0])]["bound_leg_count"] == 2
    assert receipts[str(folders[1])]["bound_leg_count"] == 1

    mixed = [leg(folders[0]), leg(folders[0], snapshot_id="wrong")]
    blocked = exchange_economics.bind_legs_to_run_snapshots(
        mixed,
        required=True,
    )

    assert blocked["ok"] is False
    assert blocked["bound_leg_count"] == 0
    assert blocked["missing_leg_count"] == 2
    assert all(row["exchange_economics_bound"] is False for row in mixed)


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
