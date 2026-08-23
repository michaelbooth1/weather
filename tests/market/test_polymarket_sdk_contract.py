"""Exact published-wheel contract for the optional International live SDK."""

from __future__ import annotations

from functools import lru_cache
import inspect
import json
import os
from importlib import metadata
from pathlib import Path
import subprocess
import sys

import pytest

from weather.market.mm_official_transport import build_l2_hmac_signature


REPO_ROOT = Path(__file__).resolve().parents[2]
OVERLAY_MANIFEST = (
    REPO_ROOT / "scripts" / "ops" / "international_live_templates"
    / "sdk_overlay_manifest.json"
)
OVERLAY_MANIFEST_SHA256 = (
    "2044d0570d38c34057c520ab19bfcc114c751fe8c76f97091b605acc1deecd13"
)
REQUIRE_LIVE_SDK = os.environ.get("WEATHER_REQUIRE_LIVE_SDK_CONTRACT") == "1"
EXPECTED_VERSION = "0.6.0"

polymarket = None
ApiKeyCreds = SecureClient = sdk_hmac = None
if not REQUIRE_LIVE_SDK:
    try:
        import polymarket
        from polymarket import ApiKeyCreds, SecureClient
        from polymarket._internal.hmac import build_hmac_signature as sdk_hmac
    except ModuleNotFoundError:
        pass

pytestmark = pytest.mark.skipif(
    not REQUIRE_LIVE_SDK and polymarket is None,
    reason="live dependency extra is not installed",
)


def _parameter(method, name):
    return inspect.signature(method).parameters[name]


def _direct_snapshot():
    credentials = ApiKeyCreds(
        key="api-key-secret-marker",
        secret="c2VjcmV0",
        passphrase="passphrase-secret-marker",
    )
    representation = repr(credentials)
    arguments = {
        "secret": "c2VjcmV0", "timestamp": 1_765_000_000,
        "method": "POST", "path": "/heartbeats", "body": None,
    }
    methods = (
        "create_limit_order", "post_order", "list_open_orders", "get_order",
        "cancel_order", "cancel_all", "get_balance_allowance",
        "get_closed_only_mode", "get_order_book", "list_current_rewards", "close",
    )
    return {
        "version": metadata.version("polymarket-client"),
        "package_version": polymarket.__version__,
        "methods": {name: callable(getattr(SecureClient, name, None)) for name in methods},
        "create_private_key_kind": _parameter(SecureClient.create, "private_key").kind.name,
        "create_wallet_kind": _parameter(SecureClient.create, "wallet").kind.name,
        "create_credentials_kind": _parameter(SecureClient.create, "credentials").kind.name,
        "post_only_default": _parameter(SecureClient.create_limit_order, "post_only").default,
        "expiration_default_is_none": _parameter(
            SecureClient.create_limit_order, "expiration"
        ).default is None,
        "post_order_has_no_post_only": "post_only"
        not in inspect.signature(SecureClient.post_order).parameters,
        "order_book_token_kind": _parameter(SecureClient.get_order_book, "token_id").kind.name,
        "cancel_order_id_kind": _parameter(SecureClient.cancel_order, "order_id").kind.name,
        "balance_asset_kind": _parameter(
            SecureClient.get_balance_allowance, "asset_type"
        ).kind.name,
        "repr_redacted": all(
            marker not in representation
            for marker in ("api-key-secret-marker", "c2VjcmV0", "passphrase-secret-marker")
        ) and representation.count("<redacted>") == 3,
        "hmac_matches": build_l2_hmac_signature(**arguments) == sdk_hmac(**arguments),
        "create_hazard": "_ensure_wallet_ready" in inspect.getsource(SecureClient.create),
        "ready_hazard": "_deploy_default_deposit_wallet"
        in inspect.getsource(SecureClient._ensure_wallet_ready),
        "place_hazard": "post_order_with_allowance_recovery_sync"
        in inspect.getsource(SecureClient.place_limit_order),
        "package_path": str(Path(polymarket.__file__).resolve()),
    }


@lru_cache(maxsize=1)
def _snapshot():
    if not REQUIRE_LIVE_SDK:
        return _direct_snapshot()
    code = r"""
import inspect,json,os
from importlib import metadata
from pathlib import Path
from weather.market.live_sdk_overlay import activate_live_sdk_overlay
activation=activate_live_sdk_overlay(os.environ['OVERLAY_MANIFEST'],os.environ['OVERLAY_SHA'])
from polymarket import ApiKeyCreds,SecureClient
import polymarket
from polymarket._internal.hmac import build_hmac_signature as sdk_hmac
from weather.market.mm_official_transport import build_l2_hmac_signature
def parameter(method,name): return inspect.signature(method).parameters[name]
credentials=ApiKeyCreds(key='api-key-secret-marker',secret='c2VjcmV0',passphrase='passphrase-secret-marker')
representation=repr(credentials)
arguments={'secret':'c2VjcmV0','timestamp':1765000000,'method':'POST','path':'/heartbeats','body':None}
methods=('create_limit_order','post_order','list_open_orders','get_order','cancel_order','cancel_all','get_balance_allowance','get_closed_only_mode','get_order_book','list_current_rewards','close')
payload={
'version':metadata.version('polymarket-client'),'package_version':polymarket.__version__,
'methods':{name:callable(getattr(SecureClient,name,None)) for name in methods},
'create_private_key_kind':parameter(SecureClient.create,'private_key').kind.name,
'create_wallet_kind':parameter(SecureClient.create,'wallet').kind.name,
'create_credentials_kind':parameter(SecureClient.create,'credentials').kind.name,
'post_only_default':parameter(SecureClient.create_limit_order,'post_only').default,
'expiration_default_is_none':parameter(SecureClient.create_limit_order,'expiration').default is None,
'post_order_has_no_post_only':'post_only' not in inspect.signature(SecureClient.post_order).parameters,
'order_book_token_kind':parameter(SecureClient.get_order_book,'token_id').kind.name,
'cancel_order_id_kind':parameter(SecureClient.cancel_order,'order_id').kind.name,
'balance_asset_kind':parameter(SecureClient.get_balance_allowance,'asset_type').kind.name,
'repr_redacted':all(x not in representation for x in ('api-key-secret-marker','c2VjcmV0','passphrase-secret-marker')) and representation.count('<redacted>')==3,
'hmac_matches':build_l2_hmac_signature(**arguments)==sdk_hmac(**arguments),
'create_hazard':'_ensure_wallet_ready' in inspect.getsource(SecureClient.create),
'ready_hazard':'_deploy_default_deposit_wallet' in inspect.getsource(SecureClient._ensure_wallet_ready),
'place_hazard':'post_order_with_allowance_recovery_sync' in inspect.getsource(SecureClient.place_limit_order),
'package_path':str(Path(polymarket.__file__).resolve()),'activation':activation}
print(json.dumps(payload,sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "OVERLAY_MANIFEST": str(OVERLAY_MANIFEST),
            "OVERLAY_SHA": OVERLAY_MANIFEST_SHA256,
        },
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("isolated pinned live SDK contract failed")
    return json.loads(result.stdout)


def test_published_wheel_version_and_required_secure_client_surface():
    snapshot = _snapshot()
    assert snapshot["version"] == snapshot["package_version"] == EXPECTED_VERSION
    assert all(snapshot["methods"].values())
    assert snapshot["create_private_key_kind"] == "KEYWORD_ONLY"
    assert snapshot["create_wallet_kind"] == "KEYWORD_ONLY"
    assert snapshot["create_credentials_kind"] == "KEYWORD_ONLY"
    assert snapshot["post_only_default"] is False
    assert snapshot["expiration_default_is_none"] is True
    assert snapshot["post_order_has_no_post_only"] is True
    assert snapshot["order_book_token_kind"] == "KEYWORD_ONLY"
    assert snapshot["cancel_order_id_kind"] == "KEYWORD_ONLY"
    assert snapshot["balance_asset_kind"] == "KEYWORD_ONLY"
    if REQUIRE_LIVE_SDK:
        assert snapshot["activation"]["post_import_revalidation"] == "PASS"
        assert "polymarket" not in sys.modules
        assert snapshot["activation"]["overlay"]["root"] not in sys.path


def test_api_credentials_repr_redacts_every_secret_field():
    assert _snapshot()["repr_redacted"] is True


def test_repository_heartbeat_hmac_matches_the_published_sdk():
    assert _snapshot()["hmac_matches"] is True


def test_convenience_surfaces_retain_the_hazards_the_adapter_avoids():
    snapshot = _snapshot()
    assert snapshot["create_hazard"] is True
    assert snapshot["ready_hazard"] is True
    assert snapshot["place_hazard"] is True
