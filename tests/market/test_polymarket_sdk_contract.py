"""Exact published-wheel contract for the optional International live SDK."""

from __future__ import annotations

import inspect
import os
from importlib import metadata

import pytest


try:
    import polymarket
    from polymarket import ApiKeyCreds, SecureClient
    from polymarket._internal.hmac import build_hmac_signature as sdk_hmac
except ModuleNotFoundError as exc:
    if os.environ.get("WEATHER_REQUIRE_LIVE_SDK_CONTRACT") == "1":
        raise RuntimeError(
            "production-host exact suite requires the pinned live SDK contract"
        ) from exc
    polymarket = None
    ApiKeyCreds = SecureClient = sdk_hmac = None

pytestmark = pytest.mark.skipif(
    polymarket is None,
    reason="live dependency extra is not installed",
)

from weather.market.mm_official_transport import (  # noqa: E402
    build_l2_hmac_signature,
)


EXPECTED_VERSION = "0.6.0"


def _parameter(method, name):
    return inspect.signature(method).parameters[name]


def test_published_wheel_version_and_required_secure_client_surface():
    assert metadata.version("polymarket-client") == EXPECTED_VERSION
    assert polymarket.__version__ == EXPECTED_VERSION

    for name in (
        "create_limit_order",
        "post_order",
        "list_open_orders",
        "get_order",
        "cancel_order",
        "cancel_all",
        "get_balance_allowance",
        "get_closed_only_mode",
        "get_order_book",
        "list_current_rewards",
        "close",
    ):
        assert callable(getattr(SecureClient, name, None)), name

    assert _parameter(SecureClient.create, "private_key").kind is inspect.Parameter.KEYWORD_ONLY
    assert _parameter(SecureClient.create, "wallet").kind is inspect.Parameter.KEYWORD_ONLY
    assert _parameter(SecureClient.create, "credentials").kind is inspect.Parameter.KEYWORD_ONLY
    assert _parameter(SecureClient.create_limit_order, "post_only").default is False
    assert _parameter(SecureClient.create_limit_order, "expiration").default is None
    assert "post_only" not in inspect.signature(SecureClient.post_order).parameters
    assert _parameter(SecureClient.get_order_book, "token_id").kind is inspect.Parameter.KEYWORD_ONLY
    assert _parameter(SecureClient.cancel_order, "order_id").kind is inspect.Parameter.KEYWORD_ONLY
    assert _parameter(SecureClient.get_balance_allowance, "asset_type").kind is inspect.Parameter.KEYWORD_ONLY


def test_api_credentials_repr_redacts_every_secret_field():
    credentials = ApiKeyCreds(
        key="api-key-secret-marker",
        secret="c2VjcmV0",
        passphrase="passphrase-secret-marker",
    )

    representation = repr(credentials)
    assert "api-key-secret-marker" not in representation
    assert "c2VjcmV0" not in representation
    assert "passphrase-secret-marker" not in representation
    assert representation.count("<redacted>") == 3


def test_repository_heartbeat_hmac_matches_the_published_sdk():
    arguments = {
        "secret": "c2VjcmV0",
        "timestamp": 1_765_000_000,
        "method": "POST",
        "path": "/heartbeats",
        "body": None,
    }

    assert build_l2_hmac_signature(**arguments) == sdk_hmac(**arguments)


def test_convenience_surfaces_retain_the_hazards_the_adapter_avoids():
    create_source = inspect.getsource(SecureClient.create)
    ready_source = inspect.getsource(SecureClient._ensure_wallet_ready)
    place_source = inspect.getsource(SecureClient.place_limit_order)

    assert "_ensure_wallet_ready" in create_source
    assert "_deploy_default_deposit_wallet" in ready_source
    assert "post_order_with_allowance_recovery_sync" in place_source
