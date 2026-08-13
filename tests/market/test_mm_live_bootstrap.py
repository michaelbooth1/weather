import json

from weather.market.mm_live_bootstrap import (
    account_snapshot_sha256,
    collect_platform_bootstrap_payload,
    load_platform_bootstrap_gate,
)
from weather.market.mm_geoblock import collect_official_geoblock_evidence


NOW = "2026-08-13T19:00:00+00:00"
TARGET_DATE = "2026-08-13"
ADDRESS = "0x0000000000000000000000000000000000000001"
CONDITION_ID = "0x" + "1" * 64
TOKEN_ID = "12345"


def geoblock_evidence(*, country="CH", region="ZH", blocked=False):
    class Response:
        status = 200

        def read(self, _limit):
            return json.dumps({
                "blocked": blocked,
                "country": country,
                "region": region,
                "ip": "203.0.113.8",
            }).encode("utf-8")

        def close(self):
            pass

    return collect_official_geoblock_evidence(
        opener=lambda _request, timeout: Response(),
        proxy_detector=lambda: {},
        now=NOW,
    )


def stage0_identity():
    return {
        "schema_version": "mm_stage0_client_identity_v0.1",
        "operator_authorization": "INTERNATIONAL_POLYMARKET_STAGE0_READ_ONLY",
        "platform": "polymarket_global",
        "international_platform_confirmed": True,
        "physical_location_matches_geoblock_confirmed": True,
        "geoblock_circumvention_absent_confirmed": True,
        "geographic_eligibility": geoblock_evidence(),
        "clob_host": "https://clob.polymarket.com",
        "settlement_unit": "pUSD",
        "chain_id": 137,
        "sdk_distribution": "py-clob-client-v2",
        "sdk_version": "1.1.0",
        "signature_type": "POLY_1271",
        "signature_type_id": 3,
        "funder_address": ADDRESS,
        "isolated_pilot_wallet": True,
        "pilot_wallet_max_funding_usdc": 100,
    }


def bootstrap_payload():
    payload = {
        "schema_version": "mm_platform_bootstrap_v0.1",
        "status": "PASS",
        "verified_at_utc": NOW,
        "verified_for_target_date": TARGET_DATE,
        "max_age_hours": 1,
        "platform": "polymarket_global",
        "international_platform_confirmed": True,
        "physical_location_matches_geoblock_confirmed": True,
        "geoblock_circumvention_absent_confirmed": True,
        "geographic_eligibility": geoblock_evidence(),
        "api_base_url": "https://polymarket.com",
        "clob_host": "https://clob.polymarket.com",
        "settlement_unit": "pUSD",
        "wallet_type": "deposit_wallet",
        "signature_type": "POLY_1271",
        "signature_type_id": 3,
        "funder_address": ADDRESS,
        "wallet_identity": {
            "private_key_signer_address": ADDRESS,
            "order_signer_address": ADDRESS,
            "api_key_owner_address": ADDRESS,
            "api_key_authentication_verified": True,
            "signed_order_preview_verified": True,
            "signed_order_preview_sha256": "e" * 64,
            "signed_order_preview_signature_retained": False,
            "consistency_verified": True,
        },
        "isolated_pilot_wallet": True,
        "pilot_wallet_max_funding_usdc": 100,
        "sdk_contract": {
            "distribution": "py-clob-client-v2",
            "version": "1.1.0",
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
        "market_snapshot": {
            "condition_id": CONDITION_ID,
            "token_id": TOKEN_ID,
            "book_verified": True,
            "fee_eligibility_verified": True,
            "min_order_size": 5,
            "tick_size": 0.01,
            "neg_risk": False,
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
            "endpoint": "/v1/heartbeats",
            "endpoint_verified": True,
            "initial_empty_id_verified": True,
            "rotating_id_chain_verified": True,
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
            "https://github.com/Polymarket/py-clob-client-v2/tree/v1.1.0",
            "https://docs.polymarket.com/api-reference/authentication",
            "https://docs.polymarket.com/api-reference/core/get-current-positions-for-a-user",
            "https://docs.polymarket.com/api-reference/wss/user",
            "https://docs.polymarket.com/trading/orders/overview",
            "https://docs.polymarket.com/trading/fees",
            "https://docs.polymarket.com/programs/maker-rebates",
            "https://docs.polymarket.com/concepts/pusd",
            "https://docs.polymarket.com/api-reference/geoblock",
        ],
    }
    payload["account_snapshot"]["snapshot_sha256"] = account_snapshot_sha256(
        payload["account_snapshot"]
    )
    return payload


def write_payload(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_bootstrap_gate_accepts_fresh_exact_international_read_only_proof(tmp_path):
    path = write_payload(tmp_path / "bootstrap.json", bootstrap_payload())

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


def test_collector_converts_atomic_collateral_and_produces_passing_gate(tmp_path):
    class Client:
        def get_address(self):
            return ADDRESS

    class UserStream:
        def bootstrap_evidence(self):
            return {
                "account_wide_subscription_sent": True,
                "server_pong_observed": True,
                "transport_active": True,
                "subscription_shape_sha256": "b" * 64,
                "journal_sha256": "c" * 64,
                "heartbeat_seconds": 10,
                "inbound_silence_seconds": 30,
                "transport_state": "TRANSPORT_CONNECTED_UNPROVEN",
                "secret_values_redacted": True,
            }

    class Adapter:
        supports_trading = True
        maker_address = ADDRESS
        condition_id = CONDITION_ID
        token_id = TOKEN_ID
        client = Client()

        def __init__(self):
            self.heartbeat_ids = []

        def balances(self):
            return {"balance": "100000000"}

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
                "best_bid": "0.49",
                "best_ask": "0.51",
            }

        def fees(self):
            return {"token_id": TOKEN_ID, "fee_rate_bps": 500}

        def preview_signed_order(self, intent, *, expected_signature_type_id):
            assert intent == {
                "token_id": TOKEN_ID,
                "price": "0.01",
                "size": "5",
                "side": "BUY",
                "expiration": 0,
            }
            return {
                "status": "VERIFIED_NON_POSTING_PREVIEW",
                "signer_address": ADDRESS,
                "maker_address": ADDRESS,
                "token_id": TOKEN_ID,
                "signature_type_id": expected_signature_type_id,
                "signed_order_sha256": "e" * 64,
                "signature_observed": True,
                "signature_retained": False,
            }

        def heartbeat(self, heartbeat_id):
            self.heartbeat_ids.append(heartbeat_id)
            return {"heartbeat_id": f"hb-{len(self.heartbeat_ids)}"}

        def cancel_all(self):
            return {"canceled": []}

        def diagnostics(self):
            return {
                "sdk_distribution": "py-clob-client-v2",
                "sdk_version": "1.1.0",
                "sdk_version_pinned": True,
            }

    class Clock:
        value = 0.0

        def __call__(self):
            return self.value

        def sleep(self, seconds):
            self.value += seconds

    clock = Clock()
    payload = collect_platform_bootstrap_payload(
        Adapter(),
        UserStream(),
        stage0_identity(),
        target_date=TARGET_DATE,
        requested_budget_usdc=100,
        secret_hygiene={
            "credentials_by_reference_verified": True,
            "direct_secret_environment_absent_verified": True,
            "diagnostic_redaction_verified": True,
        },
        now=NOW,
        monotonic_clock=clock,
        sleeper=clock.sleep,
    )
    path = write_payload(tmp_path / "collected-bootstrap.json", payload)
    gate = load_platform_bootstrap_gate(
        path,
        TARGET_DATE,
        requested_budget_usdc=100,
        expected_token_id=TOKEN_ID,
        expected_condition_id=CONDITION_ID,
        now=NOW,
    )

    assert payload["account_snapshot"]["collateral_balance_usdc"] == 100.0
    assert payload["account_snapshot"]["collateral_allowance_usdc"] == 100.0
    assert payload["dead_man_heartbeat"]["rotating_id_chain_verified"] is True
    assert payload["wallet_identity"]["signed_order_preview_verified"] is True
    assert payload["wallet_identity"]["signed_order_preview_signature_retained"] is False
    assert gate["ok"], gate["missing"]


def test_bootstrap_gate_rejects_unproved_signed_order_topology(tmp_path):
    payload = bootstrap_payload()
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


def test_bootstrap_gate_rejects_us_wrong_market_over_budget_and_secret_material(tmp_path):
    payload = bootstrap_payload()
    payload["platform"] = "polymarket_us"
    payload["geographic_eligibility"] = geoblock_evidence(
        country="US",
        region="NY",
        blocked=True,
    )
    payload["physical_location_matches_geoblock_confirmed"] = False
    payload["geoblock_circumvention_absent_confirmed"] = False
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
    assert "international_jurisdiction_verified" in gate["missing"]
    assert "requested_budget_within_wallet_cap" in gate["missing"]
    assert "market_expected_token_matches" in gate["missing"]
    assert "market_expected_condition_matches" in gate["missing"]
    assert "no_secret_material" in gate["missing"]
    assert "must-not-appear" not in json.dumps(gate, sort_keys=True)


def test_bootstrap_gate_rejects_unbacked_budget_even_when_boolean_is_true(tmp_path):
    payload = bootstrap_payload()
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
    payload = bootstrap_payload()
    payload["account_snapshot"]["collateral_balance_usdc"] = 100.01
    path = write_payload(tmp_path / "bootstrap_overfunded.json", payload)

    gate = load_platform_bootstrap_gate(
        path,
        TARGET_DATE,
        requested_budget_usdc=100,
        now=NOW,
    )

    assert not gate["ok"]
    assert "account_balance_within_wallet_cap" in gate["missing"]
