import json

import pytest

from weather.market.mm_credentials import (
    build_pinned_clob_client,
    credential_secret_hygiene,
    load_global_credential_bundle,
    parse_wincred_reference,
)
from weather.market.mm_geoblock import collect_official_geoblock_evidence


REFERENCES = {
    "POLYMARKET_API_KEY_STORAGE_REF": "wincred://Weather/Polymarket/ApiKey",
    "POLYMARKET_API_SECRET_STORAGE_REF": "wincred://Weather/Polymarket/ApiSecret",
    "POLYMARKET_API_PASSPHRASE_STORAGE_REF": "wincred://Weather/Polymarket/Passphrase",
    "POLYMARKET_PRIVATE_KEY_STORAGE_REF": "wincred://Weather/Polymarket/PrivateKey",
    "POLYMARKET_FUNDER_ADDRESS": "0x0000000000000000000000000000000000000001",
}


def eligible_geoblock():
    class Response:
        status = 200

        def read(self, _limit):
            return json.dumps({
                "blocked": False,
                "country": "CH",
                "region": "ZH",
                "ip": "203.0.113.8",
            }).encode("utf-8")

        def close(self):
            pass

    return collect_official_geoblock_evidence(
        opener=lambda _request, timeout: Response(),
        proxy_detector=lambda: {},
    )


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


def test_pinned_client_factory_uses_bootstrap_identity_and_server_time():
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

    def client_factory(**kwargs):
        captured["client"] = kwargs
        return "client-object"

    client = build_pinned_clob_client(
        bundle,
        {
            "schema_version": "mm_stage0_client_identity_v0.1",
            "operator_authorization": "INTERNATIONAL_POLYMARKET_STAGE0_READ_ONLY",
            "platform": "polymarket_global",
            "international_platform_confirmed": True,
            "physical_location_matches_geoblock_confirmed": True,
            "geoblock_circumvention_absent_confirmed": True,
            "geographic_eligibility": eligible_geoblock(),
            "clob_host": "https://clob.polymarket.com",
            "settlement_unit": "pUSD",
            "chain_id": 137,
            "sdk_distribution": "py-clob-client-v2",
            "sdk_version": "1.1.0",
            "wallet_type": "deposit_wallet",
            "funder_address": REFERENCES["POLYMARKET_FUNDER_ADDRESS"],
            "signature_type": "POLY_1271",
            "signature_type_id": 3,
            "isolated_pilot_wallet": True,
            "pilot_wallet_max_funding_usdc": 100,
        },
        client_factory=client_factory,
        api_creds_factory=api_creds_factory,
    )

    assert client == "client-object"
    assert captured["client"]["host"] == "https://clob.polymarket.com"
    assert captured["client"]["chain_id"] == 137
    assert captured["client"]["signature_type"] == 3
    assert captured["client"]["use_server_time"] is True
    assert captured["client"]["retry_on_error"] is False
    assert captured["api_creds"]["api_key"] == "api-key-value"


def test_stage0_identity_rejects_missing_topology_and_secret_fields():
    values = {
        "Weather/Polymarket/ApiKey": "api-key-value",
        "Weather/Polymarket/ApiSecret": "api-secret-value",
        "Weather/Polymarket/Passphrase": "passphrase-value",
        "Weather/Polymarket/PrivateKey": "private-key-value",
    }
    bundle = load_global_credential_bundle(REFERENCES, wincred_reader=values.__getitem__)
    identity = {
        "schema_version": "mm_stage0_client_identity_v0.1",
        "operator_authorization": "INTERNATIONAL_POLYMARKET_STAGE0_READ_ONLY",
        "platform": "polymarket_global",
        "international_platform_confirmed": True,
        "physical_location_matches_geoblock_confirmed": True,
        "geoblock_circumvention_absent_confirmed": True,
        "geographic_eligibility": eligible_geoblock(),
        "clob_host": "https://clob.polymarket.com",
        "settlement_unit": "pUSD",
        "chain_id": 137,
        "sdk_distribution": "py-clob-client-v2",
        "sdk_version": "1.1.0",
        "signature_type": "POLY_1271",
        "signature_type_id": 3,
        "funder_address": REFERENCES["POLYMARKET_FUNDER_ADDRESS"],
        "isolated_pilot_wallet": True,
        "pilot_wallet_max_funding_usdc": 100,
        "private_key": "must-never-be-here",
    }

    with pytest.raises(RuntimeError, match="exact_public_schema.*secret_material_absent.*wallet_type"):
        build_pinned_clob_client(
            bundle,
            identity,
            client_factory=lambda **_kwargs: object(),
            api_creds_factory=lambda **_kwargs: object(),
        )


def test_pinned_client_factory_rejects_bootstrap_gate_in_place_of_stage0_identity():
    values = {
        "Weather/Polymarket/ApiKey": "api-key-value",
        "Weather/Polymarket/ApiSecret": "api-secret-value",
        "Weather/Polymarket/Passphrase": "passphrase-value",
        "Weather/Polymarket/PrivateKey": "private-key-value",
    }
    bundle = load_global_credential_bundle(REFERENCES, wincred_reader=values.__getitem__)

    with pytest.raises(RuntimeError, match="Stage 0 client identity is invalid"):
        build_pinned_clob_client(
            bundle,
            {"ok": True, "platform": "polymarket_global"},
            client_factory=lambda **_kwargs: object(),
            api_creds_factory=lambda **_kwargs: object(),
        )
