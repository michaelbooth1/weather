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


def test_snapshot_payload_defaults_match_current_polymarket_us_rules():
    payload = _snapshot()

    assert payload["platform"] == "polymarket_us"
    assert payload["platform_surface"] == "retail_api_and_exchange_clob"
    assert payload["source_urls"] == [
        "https://docs.polymarket.us/fees",
        "https://docs.polymarket.us/incentives/liquidity",
    ]
    assert payload["fee_model"]["taker_fee_rate"] == 0.05
    assert payload["fee_model"]["maker_fee_rate"] == 0.0
    assert payload["maker_rebate"]["pool_share"] == 0.25
    assert payload["maker_rebate"]["theta_equivalent"] == 0.0125
    assert payload["liquidity_rewards"]["formula"] == "score = discount_factor ** ticks_from_best_price * order_size"
    assert payload["liquidity_rewards"]["discount_factor_default"] == 0.3
    assert payload["liquidity_rewards"]["target_size_default_contracts"] == 10000
    assert payload["market_rules"]["tick_size"] == 0.005
    assert payload["market_rules"]["min_order_size"] == 0.01
    assert payload["market_rules"]["market_specific_fields_required"] is True


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
    current = _snapshot(taker_fee_rate=0.06, tick_size=0.01, min_order_size=5.0)
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


def test_template_prepares_current_source_verified_snapshot():
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

    assert gate["status"] == "PASS"
    assert gate["evidence_basis"] == exchange_economics.CURRENT_EVIDENCE_BASIS
    assert payload["source_hash"] == template["source_hash"]
    assert payload["fee_model"]["taker_fee_rate"] == 0.05
    assert payload["fee_model"]["taker_fee_model"] == "polymarket_symmetric_price_v1"


def test_publish_snapshot_from_template_validates_before_overwrite(tmp_path):
    template = exchange_economics.load_snapshot_template()
    template["fee_model"].pop("taker_fee_rate")
    template["fee_model"].pop("theta")
    template_path = _write(tmp_path / "template.json", template)
    snapshot_path = tmp_path / "exchange.json"
    snapshot_path.write_text('{"keep": true}', encoding="utf-8")

    with pytest.raises(ValueError, match="taker_fee_rate_recorded"):
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

    published = exchange_economics.publish_snapshot_from_template(
        snapshot_path=snapshot_path,
        target_date=TARGET_DATE,
        now=NOW,
    )
    accepted = exchange_economics.accept_snapshot_baseline(
        snapshot_path=snapshot_path,
        accepted_snapshot_path=accepted_path,
        drift_report_path=drift_path,
        target_date=TARGET_DATE,
        now=NOW,
    )

    assert published["status"] == "PASS"
    assert accepted["status"] == "PASS"
    assert accepted["drift"]["accepted_snapshot_present"] is True
    assert accepted["drift"]["rescore_required"] is False

    current = json.loads(snapshot_path.read_text(encoding="utf-8"))
    current["fee_model"]["taker_fee_rate"] = 0.06
    current["exchange_economics_hash"] = exchange_economics.snapshot_hash(current)
    snapshot_path.write_text(json.dumps(current), encoding="utf-8")

    report = exchange_economics.build_drift_report(
        snapshot_path,
        accepted_path,
        target_date=TARGET_DATE,
        now=NOW,
    )

    assert report["status"] == "BLOCK"
    assert report["rescore_required"] is True
    assert {row["field"] for row in report["material_changes"]} == {"fee_model"}
