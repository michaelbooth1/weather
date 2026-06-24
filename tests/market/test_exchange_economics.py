import json

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
