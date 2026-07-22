from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from weather.market.live_taker_canary import (
    ACTIVATION_SCHEMA_VERSION,
    CAPITAL_CEILING_USDC,
    RISK_CAPS,
    RISK_CAPS_SHA256,
    RISK_POLICY_ID,
    RISK_POLICY_SHA256,
    STATUS_SCHEMA_VERSION,
    activation_content_sha256,
    build_capital_locked_status,
    load_and_build_capital_locked_status,
    main,
    validate_activation,
    write_capital_locked_status,
)
from weather.release_artifacts import canonical_payload_sha256
from weather.market.live_taker_state import assert_secret_safe, verify_status_snapshot


NOW = datetime(2026, 7, 21, 12, tzinfo=timezone.utc)


def _readiness(*, capital_pass: bool = True) -> dict:
    release = {
        "status": "PASS",
        "release_id": "release-1",
        "manifest_sha256": "a" * 64,
        "production_capable": True,
    }
    payload = {
        "schema_version": "production_readiness_gate_v0.1",
        "generated_at_utc": NOW.isoformat(),
        "status": "PASS" if capital_pass else "BLOCK",
        "stage": "CAPITAL_CANARY" if capital_pass else "NOT_READY",
        "highest_permitted_stage": "CAPITAL_CANARY" if capital_pass else "NOT_READY",
        "release_identity": release if capital_pass else {**release, "status": "BLOCK"},
        "stage_results": {
            "CAPITAL_CANARY": {"status": "PASS" if capital_pass else "BLOCK"}
        },
        "capital_permissions": {
            "classification_only": True,
            "credential_access_permitted": False,
            "order_submission_permitted": False,
        },
        "blockers": [] if capital_pass else [{"code": "active_release_missing", "detail": "missing"}],
    }
    payload["gate_sha256"] = canonical_payload_sha256(payload)
    return payload


def _activation(**changes) -> dict:
    payload = {
        "schema_version": ACTIVATION_SCHEMA_VERSION,
        "activation_id": "canary-2026-07",
        "platform": "polymarket_global",
        "release_id": "release-1",
        "manifest_sha256": "a" * 64,
        "account_id_sha256": "b" * 64,
        "market_ids": ["market-1"],
        "capital_ceiling_usdc": CAPITAL_CEILING_USDC,
        "risk_policy_id": RISK_POLICY_ID,
        "risk_policy_sha256": RISK_POLICY_SHA256,
        "risk_caps": dict(RISK_CAPS),
        "risk_caps_sha256": RISK_CAPS_SHA256,
        "authorized_at_utc": (NOW - timedelta(hours=1)).isoformat(),
        "expires_at_utc": (NOW + timedelta(hours=4)).isoformat(),
        "reviewed_by": "operator-review",
    }
    payload.update(changes)
    payload["activation_sha256"] = activation_content_sha256(payload)
    return payload


def test_valid_activation_is_still_not_order_authority():
    readiness = _readiness()
    activation = _activation()

    assert validate_activation(
        activation,
        readiness,
        now=NOW,
        expected_platform="polymarket_global",
        expected_account_sha256="b" * 64,
    ) == []
    payload = build_capital_locked_status(readiness, activation, now=NOW)

    assert payload["schema_version"] == STATUS_SCHEMA_VERSION
    assert payload["bot"]["state"] == "LOCKED"
    assert payload["authority"]["capital_gate_status"] == "PASS"
    assert payload["authority"]["activation_status"] == "BLOCKED"
    assert payload["authority"]["order_submission_enabled"] is False
    assert payload["authority"]["credential_access_enabled"] is False
    assert payload["authority"]["credential_reference_status"] == "NOT_READ"
    assert any(
        row["code"] == "authenticated_adapter_not_implemented"
        for row in payload["blockers"]
    )
    assert any(
        row["code"] == "activation_account_identity_unverified"
        for row in payload["blockers"]
    )
    assert payload["status_sha256"] == canonical_payload_sha256(
        payload, omit=("status_sha256",)
    )
    for key, value in payload.items():
        assert_secret_safe({key: value})
    assert verify_status_snapshot(payload) is True


def test_blocked_readiness_and_missing_activation_fail_closed_with_unknown_fund():
    payload = build_capital_locked_status(_readiness(capital_pass=False), now=NOW)

    assert payload["bot"]["state"] == "LOCKED"
    assert payload["authority"]["capital_gate_status"] == "BLOCK"
    assert payload["authority"]["activation_status"] == "MISSING"
    assert payload["fund"]["starting_capital_usdc"] == "75.00"
    assert payload["fund"]["cash_available_usdc"] is None
    assert payload["fund"]["net_liquidation_value_usdc"] is None
    assert payload["positions"] == []
    assert payload["targets"] == []


def test_activation_rejects_secret_fields_and_scope_drift():
    activation = _activation(
        private_key="must-never-appear",
        capital_ceiling_usdc=76,
        platform="wrong-platform",
    )
    activation["activation_sha256"] = activation_content_sha256(activation)

    issues = validate_activation(
        activation,
        _readiness(),
        now=NOW,
        expected_platform="polymarket_global",
        expected_account_sha256="c" * 64,
    )
    codes = {row["code"] for row in issues}

    assert "activation_contains_secret_fields" in codes
    assert "activation_contains_secret_material" in codes
    assert "activation_unknown_fields" in codes
    assert "activation_capital_ceiling_mismatch" in codes
    assert "activation_platform_mismatch" in codes
    assert "activation_account_mismatch" in codes

    status = build_capital_locked_status(_readiness(), activation, now=NOW)
    assert "must-never-appear" not in json.dumps(status, sort_keys=True)
    assert status["authority"]["activation_status"] == "BLOCKED"


def test_activation_requires_exact_money_and_string_market_scope():
    activation = _activation(
        capital_ceiling_usdc="75.00000000000000000001",
        market_ids=[True],
    )

    codes = {
        row["code"]
        for row in validate_activation(
            activation,
            _readiness(),
            now=NOW,
            expected_platform="polymarket_global",
            expected_account_sha256="b" * 64,
        )
    }

    assert "activation_capital_ceiling_mismatch" in codes
    assert "activation_market_scope_invalid" in codes


def test_expired_and_tampered_activation_fail_closed():
    activation = _activation(expires_at_utc=(NOW - timedelta(seconds=1)).isoformat())
    activation["reviewed_by"] = "changed-after-hash"

    codes = {
        row["code"]
        for row in validate_activation(activation, _readiness(), now=NOW)
    }

    assert "activation_expired" in codes
    assert "activation_hash_mismatch" in codes


def test_activation_rejects_naive_authority_times():
    activation = _activation(
        authorized_at_utc="2026-07-21T11:00:00",
        expires_at_utc="2026-07-21T16:00:00",
    )

    codes = {
        row["code"]
        for row in validate_activation(
            activation,
            _readiness(),
            now=NOW,
            expected_platform="polymarket_global",
            expected_account_sha256="b" * 64,
        )
    }

    assert "activation_authorized_at_invalid" in codes
    assert "activation_expired" in codes


def test_tampered_or_authority_granting_readiness_fails_closed():
    tampered = _readiness()
    tampered["release_identity"]["release_id"] = "release-tampered"

    payload = build_capital_locked_status(tampered, _activation(), now=NOW)

    assert payload["bot"]["state"] == "LOCKED"
    assert payload["authority"]["capital_gate_status"] == "BLOCK"
    assert any(
        row["code"] == "production_readiness_hash_mismatch"
        for row in payload["blockers"]
    )

    authority_granting = _readiness()
    authority_granting["capital_permissions"]["order_submission_permitted"] = True
    authority_granting["gate_sha256"] = canonical_payload_sha256(
        authority_granting,
        omit=("gate_sha256",),
    )

    payload = build_capital_locked_status(authority_granting, _activation(), now=NOW)

    assert payload["bot"]["state"] == "LOCKED"
    assert payload["authority"]["order_submission_enabled"] is False
    assert any(
        row["code"] == "production_readiness_authority_contract_mismatch"
        for row in payload["blockers"]
    )


def test_stale_readiness_fails_closed():
    readiness = _readiness()
    readiness["generated_at_utc"] = (NOW - timedelta(minutes=16)).isoformat()
    readiness["gate_sha256"] = canonical_payload_sha256(
        readiness,
        omit=("gate_sha256",),
    )

    payload = build_capital_locked_status(readiness, _activation(), now=NOW)

    assert payload["authority"]["capital_gate_status"] == "BLOCK"
    assert any(
        row["code"] == "production_readiness_stale"
        for row in payload["blockers"]
    )


def test_status_redacts_source_machine_paths():
    readiness = _readiness(capital_pass=False)
    readiness["blockers"][0]["detail"] = (
        r"missing C:\Users\Operator\private-worktree\artifact.json"
    )
    readiness["gate_sha256"] = canonical_payload_sha256(
        readiness,
        omit=("gate_sha256",),
    )

    payload = build_capital_locked_status(readiness, now=NOW)
    serialized = json.dumps(payload, sort_keys=True)

    assert "Operator" not in serialized
    assert "[LOCAL_PATH]" in serialized


def test_unreadable_inputs_do_not_fall_back_or_read_env(tmp_path):
    readiness_path = tmp_path / "readiness.json"
    readiness_path.write_text("{", encoding="utf-8")
    activation_path = tmp_path / "activation.json"

    payload = load_and_build_capital_locked_status(
        readiness_path=readiness_path,
        activation_path=activation_path,
        now=NOW,
    )

    assert payload["authority"]["order_submission_enabled"] is False
    assert payload["authority"]["credential_reference_status"] == "NOT_READ"
    assert any(row["code"] == "artifact_read_error" for row in payload["blockers"])


def test_initialize_writes_atomic_self_hashed_status(tmp_path):
    readiness_path = tmp_path / "readiness.json"
    readiness_path.write_text(json.dumps(_readiness(capital_pass=False)), encoding="utf-8")
    status_path = tmp_path / "canary" / "status.json"

    payload, written = write_capital_locked_status(
        status_path=status_path,
        readiness_path=readiness_path,
        activation_path=tmp_path / "missing-activation.json",
        now=NOW,
    )

    assert written == status_path
    assert json.loads(status_path.read_text(encoding="utf-8")) == payload
    assert payload["authority"]["order_submission_enabled"] is False


def test_cli_has_no_live_or_credential_arguments(tmp_path, capsys):
    readiness_path = tmp_path / "readiness.json"
    readiness_path.write_text(json.dumps(_readiness(capital_pass=False)), encoding="utf-8")
    status_path = tmp_path / "status.json"

    result = main(
        [
            "initialize",
            "--readiness",
            str(readiness_path),
            "--activation",
            str(tmp_path / "missing.json"),
            "--status-out",
            str(status_path),
        ]
    )
    output = capsys.readouterr().out

    assert result == 0
    assert status_path.is_file()
    assert '"order_submission_enabled": false' in output
    assert "private_key" not in output.lower()


def test_cli_refuses_env_input_and_output_paths(tmp_path, capsys):
    env_path = tmp_path / ".env"
    sentinel = "credential-sentinel-that-must-survive"
    env_path.write_text(sentinel, encoding="utf-8")

    result = main(
        [
            "status",
            "--readiness",
            str(env_path),
            "--activation",
            str(tmp_path / "missing.json"),
        ]
    )
    output = capsys.readouterr().out

    assert result == 0
    assert sentinel not in output
    assert "env_path_refused" in output
    assert env_path.read_text(encoding="utf-8") == sentinel

    with pytest.raises(ValueError, match="env file"):
        main(
            [
                "initialize",
                "--readiness",
                str(tmp_path / "missing.json"),
                "--status-out",
                str(env_path),
            ]
        )
    assert env_path.read_text(encoding="utf-8") == sentinel


def test_preflight_exit_is_blocked_even_with_valid_evidence(tmp_path):
    readiness_path = tmp_path / "readiness.json"
    activation_path = tmp_path / "activation.json"
    readiness_path.write_text(json.dumps(_readiness()), encoding="utf-8")
    activation_path.write_text(json.dumps(_activation()), encoding="utf-8")

    assert (
        main(
            [
                "preflight",
                "--readiness",
                str(readiness_path),
                "--activation",
                str(activation_path),
            ]
        )
        == 3
    )
