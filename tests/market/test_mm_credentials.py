import pytest

from weather.market.mm_credentials import (
    build_unified_clob_client,
    credential_secret_hygiene,
    load_global_credential_bundle,
    parse_wincred_reference,
)
REFERENCES = {
    "POLYMARKET_API_KEY_STORAGE_REF": "wincred://Weather/Polymarket/ApiKey",
    "POLYMARKET_API_SECRET_STORAGE_REF": "wincred://Weather/Polymarket/ApiSecret",
    "POLYMARKET_API_PASSPHRASE_STORAGE_REF": "wincred://Weather/Polymarket/Passphrase",
    "POLYMARKET_PRIVATE_KEY_STORAGE_REF": "wincred://Weather/Polymarket/PrivateKey",
    "POLYMARKET_FUNDER_ADDRESS": "0x0000000000000000000000000000000000000001",
}
SIGNER = "0x" + "2" * 40


def test_wincred_reference_parser_rejects_embedded_material():
    assert parse_wincred_reference("wincred://Weather/Polymarket/ApiKey") == (
        "Weather/Polymarket/ApiKey"
    )
    with pytest.raises(ValueError, match="must use wincred"):
        parse_wincred_reference("vault://Weather/Polymarket/ApiKey")
    with pytest.raises(ValueError, match="must not contain"):
        parse_wincred_reference("wincred://user:secret@Weather/ApiKey")


def test_global_bundle_loads_only_references_and_has_redacted_repr():
    values = {
        "Weather/Polymarket/ApiKey": "api-key-value",
        "Weather/Polymarket/ApiSecret": "api-secret-value",
        "Weather/Polymarket/Passphrase": "passphrase-value",
        "Weather/Polymarket/PrivateKey": "private-key-value",
    }
    bundle = load_global_credential_bundle(
        REFERENCES,
        wincred_reader=values.__getitem__,
    )

    assert bundle.api_key == "api-key-value"
    serialized = repr(bundle)
    assert "api-key-value" not in serialized
    assert "api-secret-value" not in serialized
    assert "private-key-value" not in serialized

    with pytest.raises(RuntimeError, match="storage references"):
        load_global_credential_bundle(
            {**REFERENCES, "POLYMARKET_PRIVATE_KEY": "direct-secret"},
            wincred_reader=values.__getitem__,
        )

    hygiene = credential_secret_hygiene(REFERENCES)
    assert hygiene["credentials_by_reference_verified"] is True
    assert hygiene["direct_secret_environment_absent_verified"] is True
    assert hygiene["diagnostic_redaction_verified"] is True


def test_unified_client_factory_requires_deployed_wallet_and_verifies_topology():
    values = {
        "Weather/Polymarket/ApiKey": "api-key-value",
        "Weather/Polymarket/ApiSecret": "api-secret-value",
        "Weather/Polymarket/Passphrase": "passphrase-value",
        "Weather/Polymarket/PrivateKey": "private-key-value",
    }
    bundle = load_global_credential_bundle(REFERENCES, wincred_reader=values.__getitem__)
    captured = {}

    def api_creds_factory(**kwargs):
        captured["api_creds"] = kwargs
        return "api-creds-object"

    class Client:
        signer = "0x" + "2" * 40
        closed = False

        def __init__(self, wallet_type):
            self.wallet = REFERENCES["POLYMARKET_FUNDER_ADDRESS"]
            self.wallet_type = wallet_type

        def close(self):
            self.closed = True

    expected_wallet_type = ["DEPOSIT_WALLET"]

    def client_factory(**kwargs):
        captured["client"] = kwargs
        return Client(expected_wallet_type[0])

    def wallet_deployed_reader(wallet, signature_type_id):
        captured["deployment"] = (wallet, signature_type_id)
        return True

    identity = {
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
        "funder_address": REFERENCES["POLYMARKET_FUNDER_ADDRESS"],
        "signature_type": "POLY_1271",
        "signature_type_id": 3,
        "isolated_pilot_wallet": True,
        "pilot_wallet_max_funding_usdc": 100,
    }
    client = build_unified_clob_client(
        bundle,
        identity,
        client_factory=client_factory,
        api_creds_factory=api_creds_factory,
        wallet_deployed_reader=wallet_deployed_reader,
        expected_signer_address=SIGNER,
        account_deriver=lambda _key: SIGNER,
    )

    assert client.wallet_type == "DEPOSIT_WALLET"
    assert captured["client"] == {
        "private_key": "private-key-value",
        "wallet": REFERENCES["POLYMARKET_FUNDER_ADDRESS"],
        "credentials": "api-creds-object",
    }
    assert captured["deployment"] == (
        REFERENCES["POLYMARKET_FUNDER_ADDRESS"],
        3,
    )
    assert captured["api_creds"]["key"] == "api-key-value"
    assert captured["api_creds"]["secret"] == "api-secret-value"
    assert captured["api_creds"]["passphrase"] == "passphrase-value"

    identity["wallet_type"] = "gnosis_safe"
    identity["signature_type"] = "POLY_GNOSIS_SAFE"
    identity["signature_type_id"] = 2
    expected_wallet_type[0] = "GNOSIS_SAFE"
    build_unified_clob_client(
        bundle,
        identity,
        client_factory=client_factory,
        api_creds_factory=api_creds_factory,
        wallet_deployed_reader=wallet_deployed_reader,
        expected_signer_address=SIGNER,
        account_deriver=lambda _key: SIGNER,
    )
    assert captured["deployment"][1] == 2


def test_unified_client_factory_refuses_to_invoke_sdk_for_an_unproven_wallet():
    values = {
        "Weather/Polymarket/ApiKey": "api-key-value",
        "Weather/Polymarket/ApiSecret": "api-secret-value",
        "Weather/Polymarket/Passphrase": "passphrase-value",
        "Weather/Polymarket/PrivateKey": "private-key-value",
    }
    bundle = load_global_credential_bundle(REFERENCES, wincred_reader=values.__getitem__)
    identity = {
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
        "funder_address": REFERENCES["POLYMARKET_FUNDER_ADDRESS"],
        "signature_type": "POLY_1271",
        "signature_type_id": 3,
        "isolated_pilot_wallet": True,
        "pilot_wallet_max_funding_usdc": 100,
    }
    invoked = []

    with pytest.raises(RuntimeError, match="proven deployed"):
        build_unified_clob_client(
            bundle,
            identity,
            client_factory=lambda **kwargs: invoked.append(kwargs),
            api_creds_factory=lambda **kwargs: kwargs,
            wallet_deployed_reader=lambda _wallet, _signature_type: False,
            expected_signer_address=SIGNER,
            account_deriver=lambda _key: SIGNER,
        )

    assert invoked == []


def test_unified_client_refuses_rotated_private_signer_before_any_sdk_or_write():
    values = {
        "Weather/Polymarket/ApiKey": "api-key-value",
        "Weather/Polymarket/ApiSecret": "api-secret-value",
        "Weather/Polymarket/Passphrase": "passphrase-value",
        "Weather/Polymarket/PrivateKey": "rotated-private-key",
    }
    bundle = load_global_credential_bundle(REFERENCES, wincred_reader=values.__getitem__)
    invoked = []

    with pytest.raises(RuntimeError, match="differs from the sealed manifest"):
        build_unified_clob_client(
            bundle,
            {},
            expected_signer_address=SIGNER,
            account_deriver=lambda _key: "0x" + "3" * 40,
            client_factory=lambda **kwargs: invoked.append(kwargs),
            wallet_deployed_reader=lambda *_args: invoked.append("deployment"),
        )

    assert invoked == []


def test_unified_client_factory_closes_an_unexpected_sdk_topology():
    values = {
        "Weather/Polymarket/ApiKey": "api-key-value",
        "Weather/Polymarket/ApiSecret": "api-secret-value",
        "Weather/Polymarket/Passphrase": "passphrase-value",
        "Weather/Polymarket/PrivateKey": "private-key-value",
    }
    bundle = load_global_credential_bundle(REFERENCES, wincred_reader=values.__getitem__)
    identity = {
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
        "funder_address": REFERENCES["POLYMARKET_FUNDER_ADDRESS"],
        "signature_type": "POLY_1271",
        "signature_type_id": 3,
        "isolated_pilot_wallet": True,
        "pilot_wallet_max_funding_usdc": 100,
    }

    class Client:
        wallet = REFERENCES["POLYMARKET_FUNDER_ADDRESS"]
        signer = "0x" + "2" * 40
        wallet_type = "GNOSIS_SAFE"
        closed = False

        def close(self):
            self.closed = True

    client = Client()
    with pytest.raises(RuntimeError, match="unexpected signer/wallet topology"):
        build_unified_clob_client(
            bundle,
            identity,
            client_factory=lambda **_kwargs: client,
            api_creds_factory=lambda **kwargs: kwargs,
            wallet_deployed_reader=lambda _wallet, _signature_type: True,
            expected_signer_address=SIGNER,
            account_deriver=lambda _key: SIGNER,
        )

    assert client.closed is True


def test_stage0_identity_rejects_missing_topology_and_secret_fields():
    values = {
        "Weather/Polymarket/ApiKey": "api-key-value",
        "Weather/Polymarket/ApiSecret": "api-secret-value",
        "Weather/Polymarket/Passphrase": "passphrase-value",
        "Weather/Polymarket/PrivateKey": "private-key-value",
    }
    bundle = load_global_credential_bundle(REFERENCES, wincred_reader=values.__getitem__)
    identity = {
        "schema_version": "mm_stage0_client_identity_v0.4",
        "operator_authorization": "INTERNATIONAL_POLYMARKET_STAGE0_HEARTBEAT_AND_ACCOUNT_WIDE_CANCEL_ALL_NO_ORDER",
        "platform": "polymarket_global",
        "international_platform_confirmed": True,
        "clob_host": "https://clob.polymarket.com",
        "settlement_unit": "pUSD",
        "chain_id": 137,
        "sdk_distribution": "polymarket-client",
        "sdk_version": "0.6.0",
        "signature_type": "POLY_1271",
        "signature_type_id": 3,
        "funder_address": REFERENCES["POLYMARKET_FUNDER_ADDRESS"],
        "isolated_pilot_wallet": True,
        "pilot_wallet_max_funding_usdc": 100,
        "private_key": "must-never-be-here",
    }

    with pytest.raises(
        RuntimeError,
        match="exact_public_schema.*secret_material_absent.*pilot_wallet_signature_topology",
    ):
        build_unified_clob_client(
            bundle,
            identity,
            client_factory=lambda **_kwargs: object(),
            api_creds_factory=lambda **_kwargs: object(),
            wallet_deployed_reader=lambda _wallet, _signature_type: True,
            expected_signer_address=SIGNER,
            account_deriver=lambda _key: SIGNER,
        )


def test_unified_client_factory_rejects_bootstrap_gate_in_place_of_stage0_identity():
    values = {
        "Weather/Polymarket/ApiKey": "api-key-value",
        "Weather/Polymarket/ApiSecret": "api-secret-value",
        "Weather/Polymarket/Passphrase": "passphrase-value",
        "Weather/Polymarket/PrivateKey": "private-key-value",
    }
    bundle = load_global_credential_bundle(REFERENCES, wincred_reader=values.__getitem__)

    with pytest.raises(RuntimeError, match="Stage 0 client identity is invalid"):
        build_unified_clob_client(
            bundle,
            {"ok": True, "platform": "polymarket_global"},
            client_factory=lambda **_kwargs: object(),
            api_creds_factory=lambda **_kwargs: object(),
            wallet_deployed_reader=lambda _wallet, _signature_type: True,
            expected_signer_address=SIGNER,
            account_deriver=lambda _key: SIGNER,
        )
