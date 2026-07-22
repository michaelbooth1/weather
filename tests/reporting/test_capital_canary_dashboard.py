from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from weather.market.live_taker_canary import build_capital_locked_status
from weather.release_artifacts import canonical_payload_sha256
from weather.reporting.market.capital_canary_dashboard import (
    DASHBOARD_SCHEMA_VERSION,
    STATUS_SCHEMA_VERSION,
    load_capital_canary_dashboard,
)


NOW = datetime(2026, 7, 21, 18, 0, tzinfo=timezone.utc)


def _status(**changes) -> dict:
    payload = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "generated_at_utc": NOW.isoformat().replace("+00:00", "Z"),
        "sequence": 17,
        "status": "RUNNING",
        "status_message": "Fixture status",
        "campaign_stage": "ALPHA",
        "read_only": False,
        "actionable": True,
        "capital_locked": False,
        "positions_state_known": True,
        "portfolio_state_known": True,
        "bot": {
            "state": "SCANNING",
            "heartbeat_at_utc": NOW.isoformat().replace("+00:00", "Z"),
            "kill_switch_state": "CLEAR",
        },
        "authority": {
            "production_readiness_stage": "CAPITAL_CANARY",
            "activation_status": "ACTIVE",
            "order_submission_enabled": True,
            "platform": "fixture_exchange",
            "account_id_redacted": "sha256:0123456789ab...",
            "authorized_budget_usdc": 75.0,
            "expires_at_utc": (NOW + timedelta(hours=1)).isoformat(),
            "release_id": "release-fixture",
            "manifest_sha256": "a" * 64,
        },
        "reconciliation": {"status": "RECONCILED"},
        "fund": {
            "cash_available_usdc": 70.25,
            "cash_reserved_usdc": 1.0,
            "net_liquidation_value_usdc": 74.5,
            "realized_settlement_pnl_usdc": -0.25,
            "unrealized_executable_pnl_usdc": 0.1,
            "fees_usdc": 0.05,
            "drawdown_usdc": 0.5,
        },
        "risk": {
            "policy_id": "canary-policy-1",
            "risk_policy_sha256": "b" * 64,
            "risk_caps_sha256": "b" * 64,
            "open_max_loss_usdc": 0.75,
            "cap_utilization": {"total": 0.01},
        },
        "positions": [
            {
                "position_id": "position-1",
                "event_id": "event-1",
                "market_id": "market-1",
                "side": "YES",
                "quantity": 1.0,
                "average_entry_price": 0.9,
                "worst_case_loss_usdc": 0.9,
                "unrealized_executable_bid_pnl_usdc": 0.1,
                "settled": False,
            }
        ],
        "targets": [
            {
                "decision_id": "decision-1",
                "event_id": "event-2",
                "market_id": "market-2",
                "side": "YES",
                "executable_ask": 0.91,
                "max_loss_usdc": 0.5,
                "after_cost_edge_per_share": 0.02,
                "decision": "QUALIFIED",
            }
        ],
        "recent_activity": [
            {
                "sequence": 16,
                "event_type": "RECONCILIATION",
                "code": "account_match",
                "detail": "Account matched.",
                "occurred_at_utc": NOW.isoformat(),
            }
        ],
        "performance": {
            "market_benchmark_pnl_usdc": -0.2,
            "no_trade_benchmark_pnl_usdc": 0.0,
        },
        "ledger_high_water": {"sequence": 16, "record_hash": "c" * 64},
        "blockers": [],
        "warnings": [],
        "provenance": {"activation_sha256": "d" * 64},
    }
    payload.update(changes)
    payload["status_sha256"] = canonical_payload_sha256(
        payload, omit=("status_sha256",)
    )
    return payload


def _write_status(root, payload: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "status.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )


def test_missing_status_fails_closed_with_unknown_account_values(tmp_path):
    payload = load_capital_canary_dashboard(root=tmp_path, now=NOW)

    assert payload["schema_version"] == DASHBOARD_SCHEMA_VERSION
    assert payload["source_status"] == "NO_DATA"
    assert payload["display_state"] == "LOCKED"
    assert payload["safety"]["capital_locked"] is True
    assert payload["safety"]["order_submission_enabled"] is False
    assert payload["targets"] == []
    assert payload["positions"] == []
    assert payload["freshness"]["not_assumed_flat"] is True
    assert all(value is None for value in payload["account"].values())


def test_current_capital_locked_producer_maps_without_inventing_account_state(tmp_path):
    _write_status(tmp_path, build_capital_locked_status(None, now=NOW))

    payload = load_capital_canary_dashboard(root=tmp_path, now=NOW)

    assert payload["source_status"] == "BLOCKED"
    assert payload["display_state"] == "LOCKED"
    assert payload["heartbeat"]["freshness"] == "UNKNOWN"
    assert payload["readiness"]["classification"] == "NOT_READY"
    assert payload["safety"]["order_submission_enabled"] is False
    assert payload["account"]["capital_ceiling_usdc"] == 75.0
    assert payload["account"]["cash_usdc"] is None
    assert payload["account"]["net_liquidation_value_usdc"] is None
    assert payload["positions"] == []
    assert payload["freshness"]["position_state_known"] is False
    assert payload["freshness"]["not_assumed_flat"] is True
    assert payload["freshness"]["portfolio_data_stale"] is True


def test_fresh_verified_status_projects_separate_account_and_performance_values(tmp_path):
    _write_status(tmp_path, _status())

    payload = load_capital_canary_dashboard(root=tmp_path, now=NOW)

    assert payload["source_status"] == "FRESH"
    assert payload["display_state"] == "LIVE"
    assert payload["heartbeat"] == {
        "at_utc": "2026-07-21T18:00:00Z",
        "age_seconds": 0.0,
        "freshness": "FRESH",
    }
    assert payload["safety"]["order_submission_enabled"] is True
    assert payload["account"]["net_liquidation_value_usdc"] == 74.5
    assert payload["account"]["cash_usdc"] == 70.25
    assert payload["account"]["reserve_usdc"] == 1.0
    assert payload["account"]["unresolved_worst_case_loss_usdc"] == 0.75
    assert payload["account"]["capital_ceiling_usdc"] == 75.0
    assert payload["performance"]["settled_realized_pnl_usdc"] == -0.25
    assert payload["performance"]["unrealized_executable_bid_pnl_usdc"] == 0.1
    assert payload["performance"]["fees_usdc"] == 0.05
    assert payload["performance"]["market_following_pnl_usdc"] == -0.2
    assert payload["performance"]["no_trade_pnl_usdc"] == 0.0
    assert payload["provenance"]["policy_sha256"] == "b" * 64
    assert payload["provenance"]["risk_caps_sha256"] == "b" * 64
    assert payload["positions"][0]["position_id"] == "position-1"
    assert payload["targets"][0]["decision_id"] == "decision-1"
    assert payload["activity"][0]["code"] == "account_match"


def test_stale_status_preserves_last_known_positions_but_hides_claims(tmp_path):
    stale_time = NOW - timedelta(minutes=5)
    source = _status(
        generated_at_utc=stale_time.isoformat().replace("+00:00", "Z"),
        bot={
            "state": "SCANNING",
            "heartbeat_at_utc": stale_time.isoformat().replace("+00:00", "Z"),
            "kill_switch_state": "CLEAR",
        },
    )
    _write_status(tmp_path, source)

    payload = load_capital_canary_dashboard(
        root=tmp_path, now=NOW, max_age_seconds=30
    )

    assert payload["source_status"] == "STALE"
    assert payload["positions"][0]["position_id"] == "position-1"
    assert payload["freshness"]["position_data_stale"] is True
    assert payload["freshness"]["not_assumed_flat"] is True
    assert payload["targets"] == []
    assert payload["safety"]["order_submission_enabled"] is False
    assert payload["safety"]["capital_locked"] is True
    assert payload["safety"]["kill_switch_engaged"] is True


def test_in_flight_exposure_is_fresh_without_implying_another_order(tmp_path):
    source = _status(
        bot={
            "state": "EXPOSED",
            "heartbeat_at_utc": NOW.isoformat().replace("+00:00", "Z"),
            "kill_switch_state": "CLEAR",
        },
        authority={
            **_status()["authority"],
            "order_submission_enabled": False,
        },
    )
    _write_status(tmp_path, source)

    payload = load_capital_canary_dashboard(root=tmp_path, now=NOW)

    assert payload["source_status"] == "FRESH"
    assert payload["display_state"] == "LIVE"
    assert payload["safety"]["capital_locked"] is False
    assert payload["safety"]["kill_switch_engaged"] is False
    assert payload["safety"]["order_submission_enabled"] is False
    assert payload["targets"] == []


def test_unknown_active_campaign_stage_is_conservatively_probe(tmp_path):
    source = _status(campaign_stage=None)
    _write_status(tmp_path, source)

    payload = load_capital_canary_dashboard(root=tmp_path, now=NOW)

    assert payload["display_state"] == "PROBE"


def test_blocker_hides_targets_and_order_enabled_claim(tmp_path):
    source = _status(
        blockers=[{"code": "fee_snapshot_stale", "detail": "Economics are stale."}]
    )
    _write_status(tmp_path, source)

    payload = load_capital_canary_dashboard(root=tmp_path, now=NOW)

    assert payload["source_status"] == "BLOCKED"
    assert payload["targets"] == []
    assert payload["safety"]["order_submission_enabled"] is False
    assert payload["blockers"] == [
        {"code": "fee_snapshot_stale", "detail": "Economics are stale."}
    ]


def test_malformed_blocker_unknown_status_and_expired_activation_fail_closed(tmp_path):
    source = _status(
        status="SURPRISINGLY_FINE",
        blockers=[{}],
        authority={
            **_status()["authority"],
            "expires_at_utc": (NOW - timedelta(seconds=1)).isoformat(),
        },
    )
    _write_status(tmp_path, source)

    payload = load_capital_canary_dashboard(root=tmp_path, now=NOW)

    codes = {row["code"] for row in payload["blockers"]}
    assert payload["source_status"] == "BLOCKED"
    assert payload["targets"] == []
    assert payload["safety"]["order_submission_enabled"] is False
    assert "status_blockers_malformed" in codes
    assert "status_declared_status_unknown" in codes
    assert "status_activation_expiry_invalid" in codes


def test_readiness_classification_never_grants_authority(tmp_path):
    source = _status(
        bot={
            "state": "PREFLIGHT",
            "heartbeat_at_utc": NOW.isoformat(),
            "kill_switch_state": "ENGAGED",
        },
        authority={
            "production_readiness_stage": "CAPITAL_CANARY",
            "activation_status": "ACTIVE",
            "platform": "fixture_exchange",
            "account_id_redacted": "sha256:0123456789ab...",
            "authorized_budget_usdc": 75.0,
        },
    )
    _write_status(tmp_path, source)

    payload = load_capital_canary_dashboard(root=tmp_path, now=NOW)

    assert payload["readiness"] == {
        "classification": "CAPITAL_CANARY",
        "classification_only": True,
        "grants_authority": False,
    }
    assert payload["source_status"] == "BLOCKED"
    assert payload["targets"] == []
    assert payload["safety"]["order_submission_enabled"] is False


def test_bad_hash_and_wrong_schema_fail_closed(tmp_path):
    tampered = _status()
    tampered["targets"][0]["max_loss_usdc"] = 74.0
    _write_status(tmp_path, tampered)

    payload = load_capital_canary_dashboard(root=tmp_path, now=NOW)

    assert payload["source_status"] == "INVALID"
    assert payload["targets"] == []
    assert payload["safety"]["order_submission_enabled"] is False
    assert payload["blockers"][0]["code"] == "status_status_sha256_invalid"

    wrong_schema = _status(schema_version="untrusted_status_v9")
    _write_status(tmp_path, wrong_schema)
    payload = load_capital_canary_dashboard(root=tmp_path, now=NOW)
    assert payload["source_status"] == "INVALID"
    assert payload["blockers"][0]["code"] == "status_schema_mismatch"


def test_loader_bounds_status_bytes(tmp_path):
    _write_status(tmp_path, _status())

    payload = load_capital_canary_dashboard(
        root=tmp_path,
        now=NOW,
        max_status_bytes=64,
    )

    assert payload["source_status"] == "INVALID"
    assert payload["blockers"][0]["code"] == "status_oversized"
    assert payload["targets"] == []


def test_projection_allowlist_and_text_scrubbing_remove_secret_material(tmp_path):
    source = _status(
        private_key="top-level-secret",
        account={
            "account_address": "0xraw-wallet",
            "private_key": "nested-secret",
            "cash_usdc": None,
        },
        positions=[
            {
                "position_id": "position-1",
                "market_id": "market-1",
                "api_key": "row-secret",
                "quantity": 1,
            }
        ],
        blockers=[
                {
                    "code": "auth_fault",
                    "detail": (
                        'password=detail-secret private_key:another-secret '
                        '"api_key":"quoted-secret" Authorization: Bearer bearer-secret '
                        'POLYMARKET_PRIVATE_KEY=prefixed-secret '
                        'CLOB_API_KEY=prefixed-api-secret'
                    ),
                "credential": "mapping-secret",
            }
        ],
    )
    _write_status(tmp_path, source)

    payload = load_capital_canary_dashboard(root=tmp_path, now=NOW)
    serialized = json.dumps(payload, sort_keys=True)

    for secret in (
        "top-level-secret",
        "0xraw-wallet",
        "nested-secret",
        "row-secret",
        "detail-secret",
        "another-secret",
        "quoted-secret",
        "bearer-secret",
        "mapping-secret",
        "prefixed-secret",
        "prefixed-api-secret",
    ):
        assert secret not in serialized
    assert "[REDACTED]" in payload["blockers"][0]["detail"]
    assert payload["account"]["cash_usdc"] is None
    assert payload["account"]["net_liquidation_value_usdc"] is None


def test_raw_account_identity_is_never_projected(tmp_path):
    source = _status(
        authority={
            **_status()["authority"],
            "account_id_redacted": "0x" + "1" * 40,
        }
    )
    _write_status(tmp_path, source)

    payload = load_capital_canary_dashboard(root=tmp_path, now=NOW)

    assert payload["source_status"] == "BLOCKED"
    assert payload["account"]["redacted_account_id"] is None
    assert "0x" + "1" * 40 not in json.dumps(payload)
    assert any(
        row["code"] == "status_account_redaction_invalid"
        for row in payload["blockers"]
    )


def test_unregistered_positions_sidecar_is_ignored(tmp_path):
    _write_status(tmp_path, _status(positions=[]))
    (tmp_path / "positions.json").write_text(
        json.dumps(
            {
                "positions": [{"position_id": "untrusted-position"}],
                "private_key": "sidecar-secret",
            }
        ),
        encoding="utf-8",
    )

    payload = load_capital_canary_dashboard(root=tmp_path, now=NOW)

    assert payload["positions"] == []
    assert "sidecar-secret" not in json.dumps(payload)
