import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from weather.market import mm_geographic_eligibility as geography
from weather.market import mm_live_bootstrap as bootstrap_module
from weather.market.mm_live_bootstrap import (
    SCHEMA_VERSION,
    account_snapshot_sha256,
    collect_platform_bootstrap_payload,
    finalize_platform_bootstrap_payload,
    load_platform_bootstrap_gate,
)
NOW = "2026-08-13T19:00:00+00:00"
TARGET_DATE = "2026-08-13"
ADDRESS = "0x0000000000000000000000000000000000000001"
SIGNER_ADDRESS = "0x0000000000000000000000000000000000000002"
CONDITION_ID = "0x" + "1" * 64
TOKEN_ID = "12345"
REPO_ROOT = Path(__file__).resolve().parents[2]


def geographic_receipt(checked_at=NOW):
    checked = datetime.fromisoformat(str(checked_at)).astimezone(timezone.utc)
    decision = {"blocked": False, "country": "GB", "region": "ENG"}
    receipt = {
        "agreement": True,
        "blocker_code": None,
        "checked_at_utc": geography._iso_utc(checked),
        "eligible": True,
        "endpoint": geography.GEOBLOCK_ENDPOINT,
        "fresh_until_utc": geography._iso_utc(
            checked + timedelta(seconds=geography.MAX_RECEIPT_AGE_SECONDS)
        ),
        "freshness_max_age_seconds": geography.MAX_RECEIPT_AGE_SECONDS,
        "official": {**decision, "decision_sha256": geography._canonical_digest(decision)},
        "operator_attestation": {
            "confirmation": geography.PHYSICAL_LOCATION_CONFIRMATION,
            "no_circumvention": True,
            "physical_location_eligible": True,
        },
        "privacy": {
            "source_address_retained": False,
            "secret_values_retained": False,
        },
        "receipt_payload_sha256": None,
        "response_binding": {
            "body_bytes": 80,
            "redacted_body_sha256": geography._canonical_digest(decision),
            "content_type": "application/json",
            "final_url": geography.GEOBLOCK_ENDPOINT,
            "http_status": 200,
        },
        "schema_version": geography.RECEIPT_SCHEMA_VERSION,
        "status": "PASS",
    }
    receipt["receipt_payload_sha256"] = geography._payload_digest(receipt)
    return receipt


def stage0_identity():
    return {
        "schema_version": "mm_stage0_client_identity_v0.4",
        "operator_authorization": "INTERNATIONAL_POLYMARKET_STAGE0_HEARTBEAT_AND_ACCOUNT_WIDE_CANCEL_ALL_NO_ORDER",
        "platform": "polymarket_global",
        "international_platform_confirmed": True,
        "clob_host": "https://clob.polymarket.com",
        "settlement_unit": "pUSD",
        "chain_id": 137,
        "sdk_distribution": "polymarket-client",
        "sdk_version": "0.6.0",
        "wallet_type": "deposit_wallet",
        "signature_type": "POLY_1271",
        "signature_type_id": 3,
        "funder_address": ADDRESS,
        "isolated_pilot_wallet": True,
        "pilot_wallet_max_funding_usdc": 100,
    }


def bootstrap_payload():
    payload = {
        "schema_version": "mm_platform_bootstrap_v0.6",
        "status": "PASS",
        "verified_at_utc": NOW,
        "verified_for_target_date": TARGET_DATE,
        "max_age_hours": 1,
        "platform": "polymarket_global",
        "international_platform_confirmed": True,
        "api_base_url": "https://polymarket.com",
        "clob_host": "https://clob.polymarket.com",
        "settlement_unit": "pUSD",
        "wallet_type": "deposit_wallet",
        "signature_type": "POLY_1271",
        "signature_type_id": 3,
        "funder_address": ADDRESS,
        "wallet_identity": {
            "private_key_signer_address": SIGNER_ADDRESS,
            "order_signer_address": ADDRESS,
            "api_key_owner_address": SIGNER_ADDRESS,
            "api_key_authentication_verified": True,
            "signed_order_preview_verified": True,
            "signed_order_preview_sha256": "e" * 64,
            "signed_order_preview_signature_retained": False,
            "consistency_verified": True,
        },
        "isolated_pilot_wallet": True,
        "pilot_wallet_max_funding_usdc": 100,
        "sdk_contract": {
            "distribution": "polymarket-client",
            "version": "0.6.0",
            "exact_version_verified": True,
            "stage0_identity_verified": True,
        },
        "account_snapshot": {
            "balance_allowance_verified": True,
            "collateral_balance_usdc": 100,
            "collateral_allowance_usdc": 100,
            "snapshot_sha256": "a" * 64,
            "closed_only_mode_verified": True,
            "closed_only": False,
            "zero_open_orders_verified": True,
            "open_order_count": 0,
            "position_query_exact_scope_verified": True,
            "zero_positions_verified": True,
            "position_count": 0,
        },
        "mutation_geographic_eligibility": {
            key: value
            for key, value in geographic_receipt().items()
            if key
            in {
                "status",
                "eligible",
                "endpoint",
                "receipt_payload_sha256",
                "checked_at_utc",
                "fresh_until_utc",
                "freshness_max_age_seconds",
            }
        },
        "market_snapshot": {
            "condition_id": CONDITION_ID,
            "token_id": TOKEN_ID,
            "book_verified": True,
            "fee_rule_verified": True,
            "fee_rate_bps": 500,
            "min_order_size": 5,
            "tick_size": 0.01,
            "neg_risk": False,
            "candidate_neg_risk": False,
        },
        "user_stream": {
            "account_wide_subscription_sent": True,
            "server_pong_observed": True,
            "transport_active": True,
            "transport_state": "TRANSPORT_CONNECTED_UNPROVEN",
            "subscription_shape_sha256": "b" * 64,
            "journal_sha256": "c" * 64,
            "heartbeat_seconds": 10,
            "inbound_silence_seconds": 30,
        },
        "dead_man_heartbeat": {
            "endpoint": "/heartbeats",
            "endpoint_verified": True,
            "request_body_absent_verified": True,
            "two_acknowledgments_verified": True,
            "acknowledgment_count": 2,
            "heartbeat_acknowledgments_sha256": "f" * 64,
            "acknowledgment_verified": True,
            "cadence_seconds": 5,
        },
        "cancel_all": {
            "request_verified": True,
            "zero_open_orders_verified": True,
        },
        "secret_hygiene": {
            "credentials_by_reference_verified": True,
            "direct_secret_environment_absent_verified": True,
            "diagnostic_redaction_verified": True,
        },
        "source_urls": [
            "https://github.com/Polymarket/py-sdk/tree/c8fb84bb51e60f790239056be7be0f5cc337d2e0",
            "https://docs.polymarket.com/getting-started/migrate-from-previous-sdks",
            "https://docs.polymarket.com/api-reference/trade/send-heartbeat",
            "https://docs.polymarket.com/api-reference/authentication",
            "https://docs.polymarket.com/trading/overview",
            "https://docs.polymarket.com/api-reference/core/get-current-positions-for-a-user",
            "https://docs.polymarket.com/api-reference/wss/user",
            "https://docs.polymarket.com/trading/orders/overview",
            "https://docs.polymarket.com/trading/fees",
            "https://docs.polymarket.com/api-reference/market-data/get-fee-rate",
            "https://docs.polymarket.com/concepts/pusd",
        ],
    }
    payload["account_snapshot"]["snapshot_sha256"] = account_snapshot_sha256(
        payload["account_snapshot"]
    )
    return payload


def write_payload(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def finalized_bootstrap_payload(tmp_path, *, name="stage0", payload=None):
    payload = payload or bootstrap_payload()
    journal_path = tmp_path / f"{name}-user-stream.jsonl"
    prefix = json.dumps({"event_type": "subscription_sent", "name": name}).encode(
        "utf-8"
    ) + b"\n"
    terminal = b'{"event_type":"stream_stopped"}\n'
    journal_path.write_bytes(prefix + terminal)
    payload["user_stream"]["journal_sha256"] = hashlib.sha256(prefix).hexdigest()

    class StoppedStream:
        def __init__(self, path):
            self.journal_path = path

        def health(self):
            return {"state": "STOPPED", "failure_type": None}

        def bootstrap_evidence(self):
            return {
                "transport_active": False,
                "transport_state": "STOPPED",
                "journal_sha256": hashlib.sha256(prefix + terminal).hexdigest(),
            }

    return finalize_platform_bootstrap_payload(
        payload,
        StoppedStream(journal_path),
        now=NOW,
    )


def test_bootstrap_gate_accepts_fresh_exact_no_order_authenticated_write_proof(
    tmp_path,
):
    path = write_payload(
        tmp_path / "bootstrap.json",
        finalized_bootstrap_payload(tmp_path),
    )

    gate = load_platform_bootstrap_gate(
        path,
        TARGET_DATE,
        requested_budget_usdc=100,
        expected_token_id=TOKEN_ID,
        expected_condition_id=CONDITION_ID,
        now=NOW,
    )

    assert gate["ok"]
    assert gate["missing"] == []
    assert gate["platform"] == "polymarket_global"


def test_bootstrap_gate_refuses_the_published_v03_contract(tmp_path):
    payload = finalized_bootstrap_payload(tmp_path, name="legacy-v03")
    payload["schema_version"] = "mm_platform_bootstrap_v0.3"
    path = write_payload(tmp_path / "legacy-v03.json", payload)

    gate = load_platform_bootstrap_gate(
        path,
        TARGET_DATE,
        requested_budget_usdc=100,
        expected_token_id=TOKEN_ID,
        expected_condition_id=CONDITION_ID,
        now=NOW,
    )

    assert SCHEMA_VERSION == "mm_platform_bootstrap_v0.6"
    assert gate["ok"] is False
    assert "schema_version_supported" in gate["missing"]


def test_bootstrap_research_template_tracks_the_active_contract():
    payload = json.loads(
        (
            REPO_ROOT / "docs" / "research" / "mm_platform_bootstrap_template.json"
        ).read_text(encoding="utf-8")
    )

    assert payload["schema_version"] == SCHEMA_VERSION
    assert set(payload["mutation_geographic_eligibility"]) == {
        "status",
        "eligible",
        "endpoint",
        "receipt_payload_sha256",
        "checked_at_utc",
        "fresh_until_utc",
        "freshness_max_age_seconds",
    }
    assert payload["market_snapshot"]["fee_rule_verified"] is False
    assert "candidate_fee_rate" not in payload["market_snapshot"]
    assert payload["market_snapshot"]["candidate_neg_risk"] is None


def test_bootstrap_gate_accepts_zero_fee_but_rejects_candidate_neg_risk_drift(
    tmp_path,
):
    zero_fee = finalized_bootstrap_payload(tmp_path, name="zero-fee")
    zero_fee["market_snapshot"]["fee_rate_bps"] = 0
    zero_fee_path = write_payload(tmp_path / "zero-fee.json", zero_fee)
    zero_fee_gate = load_platform_bootstrap_gate(
        zero_fee_path,
        TARGET_DATE,
        requested_budget_usdc=100,
        expected_token_id=TOKEN_ID,
        expected_condition_id=CONDITION_ID,
        now=NOW,
    )
    assert zero_fee_gate["ok"] is True
    assert zero_fee_gate["fee_rate_bps"] == 0

    drift = finalized_bootstrap_payload(tmp_path, name="neg-risk-drift")
    drift["market_snapshot"]["neg_risk"] = True
    drift_path = write_payload(tmp_path / "neg-risk-drift.json", drift)
    drift_gate = load_platform_bootstrap_gate(
        drift_path,
        TARGET_DATE,
        requested_budget_usdc=100,
        expected_token_id=TOKEN_ID,
        expected_condition_id=CONDITION_ID,
        now=NOW,
    )
    assert drift_gate["ok"] is False
    assert "market_candidate_neg_risk_matches_current" in drift_gate["missing"]


def test_persisted_active_stream_boolean_cannot_authorize_stage1(tmp_path):
    path = write_payload(tmp_path / "unfinalized-bootstrap.json", bootstrap_payload())

    gate = load_platform_bootstrap_gate(
        path,
        TARGET_DATE,
        requested_budget_usdc=100,
        expected_token_id=TOKEN_ID,
        expected_condition_id=CONDITION_ID,
        now=NOW,
    )

    assert gate["ok"] is False
    assert "user_stream_cleanly_finalized" in gate["missing"]
    assert "user_stream_final_journal_content_bound" in gate["missing"]


def test_finite_stage0_finalizes_the_durable_user_stream_journal(tmp_path):
    journal_path = tmp_path / "stage0-user-stream.jsonl"
    prefix = b'{"event_type":"subscription_sent"}\n'
    terminal = b'{"event_type":"stream_stopped"}\n'
    journal_path.write_bytes(prefix + terminal)

    class StoppedStream:
        def __init__(self, path):
            self.journal_path = path

        def health(self):
            return {"state": "STOPPED", "failure_type": None}

        def bootstrap_evidence(self):
            return {
                "transport_active": False,
                "transport_state": "STOPPED",
                "journal_sha256": hashlib.sha256(prefix + terminal).hexdigest(),
            }

    payload = bootstrap_payload()
    payload["user_stream"]["journal_sha256"] = hashlib.sha256(prefix).hexdigest()
    finalized = finalize_platform_bootstrap_payload(
        payload,
        StoppedStream(journal_path),
        now=NOW,
    )
    path = write_payload(tmp_path / "finalized-bootstrap.json", finalized)
    gate = load_platform_bootstrap_gate(
        path,
        TARGET_DATE,
        requested_budget_usdc=100,
        expected_token_id=TOKEN_ID,
        expected_condition_id=CONDITION_ID,
        now=NOW,
    )

    assert finalized["user_stream"]["transport_active_at_collection"] is True
    assert finalized["user_stream"]["transport_state_at_collection"] == (
        "TRANSPORT_CONNECTED_UNPROVEN"
    )
    assert finalized["user_stream"]["journal_sha256_at_collection"] == hashlib.sha256(
        prefix
    ).hexdigest()
    assert finalized["user_stream"]["journal_sha256"] == hashlib.sha256(
        prefix + terminal
    ).hexdigest()
    assert finalized["user_stream"]["journal_path"] == str(journal_path.resolve())
    assert finalized["user_stream"]["transport_active"] is False
    assert gate["ok"], gate["missing"]


def test_stage0_finalizer_rejects_a_failed_stream():
    class FailedStream:
        def health(self):
            return {"state": "FAILED", "failure_type": "ConnectionError"}

        def bootstrap_evidence(self):
            return {
                "transport_active": False,
                "transport_state": "FAILED",
                "journal_sha256": "d" * 64,
            }

    with pytest.raises(RuntimeError, match="did not finalize cleanly"):
        finalize_platform_bootstrap_payload(bootstrap_payload(), FailedStream(), now=NOW)


def test_finite_stage0_gate_rejects_a_modified_final_journal(tmp_path):
    journal_path = tmp_path / "stage0-user-stream.jsonl"
    prefix = b'{"event_type":"subscription_sent"}\n'
    terminal = b'{"event_type":"stream_stopped"}\n'
    journal_path.write_bytes(prefix + terminal)

    class StoppedStream:
        def __init__(self, path):
            self.journal_path = path

        def health(self):
            return {"state": "STOPPED", "failure_type": None}

        def bootstrap_evidence(self):
            return {
                "transport_active": False,
                "transport_state": "STOPPED",
                "journal_sha256": hashlib.sha256(prefix + terminal).hexdigest(),
            }

    payload = bootstrap_payload()
    payload["user_stream"]["journal_sha256"] = hashlib.sha256(prefix).hexdigest()
    finalized = finalize_platform_bootstrap_payload(
        payload,
        StoppedStream(journal_path),
        now=NOW,
    )
    path = write_payload(tmp_path / "finalized-bootstrap.json", finalized)
    with journal_path.open("ab") as handle:
        handle.write(b'{"event_type":"tampered"}\n')

    gate = load_platform_bootstrap_gate(
        path,
        TARGET_DATE,
        requested_budget_usdc=100,
        expected_token_id=TOKEN_ID,
        expected_condition_id=CONDITION_ID,
        now=NOW,
    )

    assert gate["ok"] is False
    assert "user_stream_final_journal_content_bound" in gate["missing"]


@pytest.mark.parametrize("existing_wallet", [False, True])
@pytest.mark.parametrize("authentication_rejected", [False, True])
def test_collector_requires_current_authentication_before_bootstrap_writes(
    tmp_path,
    monkeypatch,
    existing_wallet,
    authentication_rejected,
):
    identity = stage0_identity()
    expected_balance = 275.48 if existing_wallet else 100.0
    if existing_wallet:
        identity.update(
            pilot_capital_mode="existing_wallet_test_allocation",
            pilot_test_allocation_pusd=100,
            isolated_pilot_wallet=False,
            pilot_wallet_max_funding_usdc=None,
        )
    boundary_events = []
    geography_validation_count = 0
    original_geography_validator = (
        bootstrap_module.validate_geographic_eligibility_receipt
    )

    def count_geography_validation(*args, **kwargs):
        nonlocal geography_validation_count
        geography_validation_count += 1
        return original_geography_validator(*args, **kwargs)

    monkeypatch.setattr(
        bootstrap_module,
        "validate_geographic_eligibility_receipt",
        count_geography_validation,
    )

    class Client:
        signer = SIGNER_ADDRESS

    class UserStream:
        def __init__(self, path):
            self.journal_path = path
            self.stopped = False
            self.journal_path.write_bytes(b'{"event_type":"subscription_sent"}\n')

        def bootstrap_evidence(self):
            return {
                "account_wide_subscription_sent": True,
                "server_pong_observed": True,
                "transport_active": not self.stopped,
                "subscription_shape_sha256": "b" * 64,
                "journal_sha256": hashlib.sha256(
                    self.journal_path.read_bytes()
                ).hexdigest(),
                "heartbeat_seconds": 10,
                "inbound_silence_seconds": 30,
                "transport_state": (
                    "STOPPED" if self.stopped else "TRANSPORT_CONNECTED_UNPROVEN"
                ),
                "secret_values_redacted": True,
            }

        def stop(self):
            self.stopped = True
            with self.journal_path.open("ab") as handle:
                handle.write(b'{"event_type":"stream_stopped"}\n')

        def health(self):
            return {"state": "STOPPED", "failure_type": None}

    class Adapter:
        supports_trading = True
        maker_address = ADDRESS
        condition_id = CONDITION_ID
        token_id = TOKEN_ID
        client = Client()

        def __init__(self):
            self.heartbeat_calls = 0

        def balances(self):
            if authentication_rejected:
                raise RuntimeError("current API authentication rejected")
            return {"balance": "275480000" if existing_wallet else "100000000"}

        def allowances(self):
            return {"spender-a": "100000000", "spender-b": "200000000"}

        def open_orders(self):
            return []

        def positions(self):
            return []

        def position_evidence(self, positions):
            return {
                "status": "OBSERVED",
                "query_scope": "exact_maker_condition",
                "maker_address": ADDRESS,
                "condition_id": CONDITION_ID,
                "rows": positions,
                "http_status": 200,
                "response_sha256": "d" * 64,
                "request_url": (
                    "https://data-api.polymarket.com/positions?"
                    f"user={ADDRESS}&market={CONDITION_ID}&sizeThreshold=0"
                    "&limit=500&offset=0"
                ),
            }

        def closed_only_mode(self):
            return {"closed_only": False}

        def refresh_market_rules(self):
            return {
                "token_id": TOKEN_ID,
                "min_order_size": "5",
                "tick_size": "0.01",
                "neg_risk": False,
                "fee_rate_bps": "500",
                "best_bid": "0.49",
                "best_ask": "0.51",
            }

        def fees(self):
            return {"token_id": TOKEN_ID, "fee_rate_bps": 500}

        def preview_signed_order(self, intent, *, expected_signature_type_id):
            boundary_events.append("signed_preview")
            assert intent == {
                "token_id": TOKEN_ID,
                "price": "0.01",
                "size": "5",
                "side": "BUY",
                "expiration": 0,
            }
            return {
                "status": "VERIFIED_NON_POSTING_PREVIEW",
                "client_signer_address": SIGNER_ADDRESS,
                "order_signer_address": ADDRESS,
                "maker_address": ADDRESS,
                "token_id": TOKEN_ID,
                "signature_type_id": expected_signature_type_id,
                "signed_order_sha256": "e" * 64,
                "signature_observed": True,
                "signature_retained": False,
            }

        def heartbeat(self):
            boundary_events.append("heartbeat")
            self.heartbeat_calls += 1
            return {"status": "ok"}

        def cancel_all(self):
            boundary_events.append("cancel_all")
            return {"canceled": []}

        def diagnostics(self):
            return {
                "sdk_distribution": "polymarket-client",
                "sdk_version": "0.6.0",
                "sdk_version_pinned": True,
            }

    class Clock:
        value = 0.0

        def __call__(self):
            boundary_events.append("clock")
            return self.value

        def sleep(self, seconds):
            self.value += seconds

    clock = Clock()
    user_stream = UserStream(tmp_path / "collector-user-stream.jsonl")
    bootstrap_phases = []

    def attest_at_mutation_boundary():
        boundary_events.append("geography")
        return geographic_receipt()

    def record_authenticated_write(operation):
        boundary_events.append(f"{operation}_attempt")

    collect_arguments = dict(
        target_date=TARGET_DATE,
        requested_budget_usdc=10,
        secret_hygiene={
            "credentials_by_reference_verified": True,
            "direct_secret_environment_absent_verified": True,
            "diagnostic_redaction_verified": True,
        },
        expected_candidate_neg_risk=False,
        pre_mutation_attestor=attest_at_mutation_boundary,
        progress_recorder=bootstrap_phases.append,
        authenticated_write_recorder=record_authenticated_write,
        now=NOW,
        utc_clock=lambda: datetime.fromisoformat(NOW),
        monotonic_clock=clock,
        sleeper=clock.sleep,
    )
    if authentication_rejected:
        with pytest.raises(RuntimeError, match="current API authentication rejected"):
            collect_platform_bootstrap_payload(
                Adapter(), user_stream, identity, **collect_arguments
            )
        assert bootstrap_phases[-1] == "collateral_query"
        assert boundary_events == []
        return
    payload = collect_platform_bootstrap_payload(
        Adapter(), user_stream, identity, **collect_arguments
    )
    user_stream.stop()
    payload = finalize_platform_bootstrap_payload(payload, user_stream, now=NOW)
    path = write_payload(tmp_path / "collected-bootstrap.json", payload)
    gate = load_platform_bootstrap_gate(
        path,
        TARGET_DATE,
        requested_budget_usdc=10,
        expected_token_id=TOKEN_ID,
        expected_condition_id=CONDITION_ID,
        now=NOW,
    )

    assert payload["account_snapshot"]["collateral_balance_usdc"] == expected_balance
    assert gate["pilot_capital_limit_pusd"] == 100
    assert gate["pilot_wallet_max_funding_usdc"] == (None if existing_wallet else 100)
    if existing_wallet:
        assert gate["pilot_test_allocation_pusd"] == 100
        assert gate["isolated_pilot_wallet"] is False
    assert payload["account_snapshot"]["collateral_allowance_usdc"] == 100.0
    assert payload["dead_man_heartbeat"]["two_acknowledgments_verified"] is True
    assert payload["dead_man_heartbeat"]["acknowledgment_count"] == 2
    assert payload["wallet_identity"]["signed_order_preview_verified"] is True
    assert payload["wallet_identity"]["signed_order_preview_signature_retained"] is False
    assert payload["market_snapshot"]["fee_rate_bps"] == 500.0
    assert "candidate_fee_rate" not in payload["market_snapshot"]
    assert payload["market_snapshot"]["candidate_neg_risk"] is False
    assert payload["mutation_geographic_eligibility"]["status"] == "PASS"
    assert boundary_events == [
        "signed_preview",
        "geography",
        "clock",
        "heartbeat_attempt",
        "heartbeat",
        "clock",
        "clock",
        "heartbeat_attempt",
        "heartbeat",
        "clock",
        "cancel_all_attempt",
        "cancel_all",
    ]
    assert bootstrap_phases[0] == "identity_gate"
    assert bootstrap_phases[-1] == "complete"
    assert "balance_backing" in bootstrap_phases
    assert "premutation_geography" in bootstrap_phases
    assert geography_validation_count == 4
    assert gate["ok"], gate["missing"]

    boundary_events.clear()
    failed_clock_stream = UserStream(tmp_path / "failed-clock-user-stream.jsonl")

    def fail_before_first_write():
        boundary_events.append("clock_failed")
        raise RuntimeError("clock unavailable")

    with pytest.raises(RuntimeError, match="clock unavailable"):
        collect_platform_bootstrap_payload(
            Adapter(),
            failed_clock_stream,
            identity,
            target_date=TARGET_DATE,
            requested_budget_usdc=10,
            secret_hygiene={
                "credentials_by_reference_verified": True,
                "direct_secret_environment_absent_verified": True,
                "diagnostic_redaction_verified": True,
            },
            expected_candidate_neg_risk=False,
            pre_mutation_attestor=attest_at_mutation_boundary,
            progress_recorder=lambda _phase: None,
            authenticated_write_recorder=lambda operation: boundary_events.append(
                f"{operation}_attempt"
            ),
            now=NOW,
            utc_clock=lambda: datetime.fromisoformat(NOW),
            monotonic_clock=fail_before_first_write,
            sleeper=lambda _seconds: None,
        )

    assert boundary_events == [
        "signed_preview",
        "geography",
        "clock_failed",
    ]

    boundary_events.clear()
    failed_recorder_stream = UserStream(tmp_path / "failed-recorder-user-stream.jsonl")

    def fail_write_recorder(operation):
        boundary_events.append(f"{operation}_recorder_failed")
        raise RuntimeError("write recorder unavailable")

    with pytest.raises(RuntimeError, match="write recorder unavailable"):
        collect_platform_bootstrap_payload(
            Adapter(),
            failed_recorder_stream,
            identity,
            target_date=TARGET_DATE,
            requested_budget_usdc=10,
            secret_hygiene={
                "credentials_by_reference_verified": True,
                "direct_secret_environment_absent_verified": True,
                "diagnostic_redaction_verified": True,
            },
            expected_candidate_neg_risk=False,
            pre_mutation_attestor=attest_at_mutation_boundary,
            progress_recorder=lambda _phase: None,
            authenticated_write_recorder=fail_write_recorder,
            now=NOW,
            utc_clock=lambda: datetime.fromisoformat(NOW),
            monotonic_clock=lambda: 0.0,
            sleeper=lambda _seconds: None,
        )

    assert boundary_events == [
        "signed_preview",
        "geography",
        "heartbeat_recorder_failed",
    ]


def test_bootstrap_gate_rejects_unproved_signed_order_topology(tmp_path):
    payload = finalized_bootstrap_payload(tmp_path, name="no-signed-preview")
    payload["wallet_identity"]["signed_order_preview_verified"] = False
    payload["wallet_identity"]["signed_order_preview_sha256"] = None
    path = write_payload(tmp_path / "bootstrap-no-signed-preview.json", payload)

    gate = load_platform_bootstrap_gate(
        path,
        TARGET_DATE,
        requested_budget_usdc=100.0,
        now=NOW,
    )

    assert not gate["ok"]
    assert "signed_order_preview_verified" in gate["missing"]


def test_bootstrap_gate_rejects_eoa_as_deposit_wallet_order_signer(tmp_path):
    payload = finalized_bootstrap_payload(tmp_path, name="wrong-order-signer")
    payload["wallet_identity"]["order_signer_address"] = SIGNER_ADDRESS
    path = write_payload(tmp_path / "bootstrap-wrong-order-signer.json", payload)

    gate = load_platform_bootstrap_gate(
        path,
        TARGET_DATE,
        requested_budget_usdc=100.0,
        now=NOW,
    )

    assert not gate["ok"]
    assert "order_signer_matches_wallet_topology" in gate["missing"]


def test_bootstrap_gate_rejects_same_eoa_and_deposit_wallet(tmp_path):
    payload = finalized_bootstrap_payload(tmp_path, name="same-wallet")
    payload["wallet_identity"]["private_key_signer_address"] = ADDRESS
    payload["wallet_identity"]["api_key_owner_address"] = ADDRESS
    path = write_payload(tmp_path / "bootstrap-same-wallet.json", payload)

    gate = load_platform_bootstrap_gate(
        path,
        TARGET_DATE,
        requested_budget_usdc=100.0,
        now=NOW,
    )

    assert not gate["ok"]
    assert "signer_funder_relation_matches_wallet_topology" in gate["missing"]


def test_bootstrap_gate_accepts_existing_gnosis_safe_topology(tmp_path):
    payload = bootstrap_payload()
    payload["wallet_type"] = "gnosis_safe"
    payload["signature_type"] = "POLY_GNOSIS_SAFE"
    payload["signature_type_id"] = 2
    payload["wallet_identity"]["order_signer_address"] = SIGNER_ADDRESS
    path = write_payload(
        tmp_path / "bootstrap-gnosis-safe.json",
        finalized_bootstrap_payload(tmp_path, name="gnosis-safe", payload=payload),
    )

    gate = load_platform_bootstrap_gate(
        path,
        TARGET_DATE,
        requested_budget_usdc=100.0,
        now=NOW,
    )

    assert gate["ok"], gate["missing"]


def test_bootstrap_gate_rejects_us_wrong_market_over_budget_and_secret_material(tmp_path):
    payload = finalized_bootstrap_payload(tmp_path, name="invalid")
    payload["platform"] = "polymarket_us"
    payload["international_platform_confirmed"] = False
    payload["private_key"] = "must-not-appear"
    path = write_payload(tmp_path / "bootstrap_invalid.json", payload)

    gate = load_platform_bootstrap_gate(
        path,
        TARGET_DATE,
        requested_budget_usdc=100.01,
        expected_token_id="different-token",
        expected_condition_id="different-condition",
        now=NOW,
    )

    assert not gate["ok"]
    assert "platform_is_international" in gate["missing"]
    assert "requested_budget_within_pilot_capital_limit" in gate["missing"]
    assert "market_expected_token_matches" in gate["missing"]
    assert "market_expected_condition_matches" in gate["missing"]
    assert "no_secret_material" in gate["missing"]
    assert "must-not-appear" not in json.dumps(gate, sort_keys=True)


def test_bootstrap_gate_rejects_unbacked_budget_even_when_boolean_is_true(tmp_path):
    payload = finalized_bootstrap_payload(tmp_path, name="unbacked")
    payload["account_snapshot"]["collateral_balance_usdc"] = 99.99
    payload["account_snapshot"]["collateral_allowance_usdc"] = 0
    path = write_payload(tmp_path / "bootstrap_unbacked.json", payload)

    gate = load_platform_bootstrap_gate(
        path,
        TARGET_DATE,
        requested_budget_usdc=100,
        now=NOW,
    )

    assert not gate["ok"]
    assert "account_balance_backs_requested_budget" in gate["missing"]
    assert "account_allowance_backs_requested_budget" in gate["missing"]


def test_bootstrap_gate_rejects_actual_balance_above_declared_wallet_cap(tmp_path):
    payload = finalized_bootstrap_payload(tmp_path, name="overfunded")
    payload["account_snapshot"]["collateral_balance_usdc"] = 100.01
    path = write_payload(tmp_path / "bootstrap_overfunded.json", payload)

    gate = load_platform_bootstrap_gate(
        path,
        TARGET_DATE,
        requested_budget_usdc=100,
        now=NOW,
    )

    assert not gate["ok"]
    assert "account_balance_within_capital_scope" in gate["missing"]



@pytest.mark.parametrize("balance,allowance,budget,allowed", [
    (275.48, 100, 10, True),
    (9.99, 100, 10, False),
    (275.48, 9.99, 10, False),
    (275.48, 1000, 100.01, False),
    (float("inf"), 100, 10, False),
])
def test_bootstrap_allocation_preserves_cash_and_backing_checks(
    tmp_path, balance, allowance, budget, allowed
):
    payload = finalized_bootstrap_payload(tmp_path, name="allocation")
    payload.update(
        pilot_capital_mode="existing_wallet_test_allocation",
        pilot_test_allocation_pusd=100,
        isolated_pilot_wallet=False,
        pilot_wallet_max_funding_usdc=None,
    )
    payload["account_snapshot"]["collateral_balance_usdc"] = balance
    payload["account_snapshot"]["collateral_allowance_usdc"] = allowance
    payload["account_snapshot"]["snapshot_sha256"] = account_snapshot_sha256(
        payload["account_snapshot"]
    )
    path = write_payload(tmp_path / "bootstrap-allocation.json", payload)
    gate = load_platform_bootstrap_gate(
        path, TARGET_DATE, requested_budget_usdc=budget, now=NOW
    )
    assert gate["ok"] is allowed, gate["missing"]
    assert gate["pilot_wallet_max_funding_usdc"] is None
    assert gate["pilot_capital_limit_pusd"] == 100
