"""Credential-by-reference loading for the International live probe.

Only Windows Credential Manager generic credentials are supported on the
production host. References identify vault entries; secret values must never
be supplied directly through environment variables or command arguments.
"""

from __future__ import annotations

import ctypes
import math
import os
from ctypes import wintypes
from urllib.parse import unquote, urlsplit

from weather.market.mm_exchange import credential_diagnostics
from weather.market.mm_official_adapter import (
    OFFICIAL_CLOB_DISTRIBUTION,
    OFFICIAL_CLOB_VERSION,
    require_official_clob_version,
)
from weather.market.market_making_preflight import (
    MAX_OPERATOR_PILOT_BUDGET_USDC,
    INTERNATIONAL_SETTLEMENT_UNIT,
    contains_secret_material,
    international_jurisdiction,
    non_empty_text,
    signature_type_consistent,
    valid_evm_address,
)


REFERENCE_ENV = {
    "api_key": "POLYMARKET_API_KEY_STORAGE_REF",
    "api_secret": "POLYMARKET_API_SECRET_STORAGE_REF",
    "api_passphrase": "POLYMARKET_API_PASSPHRASE_STORAGE_REF",
    "private_key": "POLYMARKET_PRIVATE_KEY_STORAGE_REF",
}
FUNDER_ENV = "POLYMARKET_FUNDER_ADDRESS"
WINCRED_SCHEME = "wincred"
STAGE0_IDENTITY_SCHEMA_VERSION = "mm_stage0_client_identity_v0.1"
STAGE0_AUTHORIZATION = "INTERNATIONAL_POLYMARKET_STAGE0_READ_ONLY"
STAGE0_IDENTITY_KEYS = {
    "schema_version",
    "operator_authorization",
    "platform",
    "international_platform_confirmed",
    "physical_location_matches_geoblock_confirmed",
    "geoblock_circumvention_absent_confirmed",
    "geographic_eligibility",
    "clob_host",
    "settlement_unit",
    "chain_id",
    "sdk_distribution",
    "sdk_version",
    "wallet_type",
    "signature_type",
    "signature_type_id",
    "funder_address",
    "isolated_pilot_wallet",
    "pilot_wallet_max_funding_usdc",
}


class GlobalCredentialBundle:
    __slots__ = ("api_key", "api_secret", "api_passphrase", "private_key", "funder")

    def __init__(self, *, api_key, api_secret, api_passphrase, private_key, funder):
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.private_key = private_key
        self.funder = funder

    def __repr__(self):
        return (
            "GlobalCredentialBundle(api_key=<redacted>, api_secret=<redacted>, "
            "api_passphrase=<redacted>, private_key=<redacted>, funder=<public>)"
        )


def parse_wincred_reference(reference):
    parsed = urlsplit(str(reference or ""))
    if parsed.scheme.lower() != WINCRED_SCHEME:
        raise ValueError("credential reference must use wincred://")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("credential reference must not contain userinfo, query, or fragment")
    target = unquote((parsed.netloc + parsed.path).strip("/"))
    if not target:
        raise ValueError("credential reference must name a Windows Credential Manager target")
    if any(ord(character) < 32 for character in target):
        raise ValueError("credential reference target must not contain control characters")
    return target


def _read_windows_generic_credential(target):
    if os.name != "nt":
        raise RuntimeError("wincred:// references are supported only on Windows")

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    credential_pointer = ctypes.POINTER(CREDENTIAL)()
    cred_read = advapi32.CredReadW
    cred_read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    cred_read.restype = wintypes.BOOL
    cred_free = advapi32.CredFree
    cred_free.argtypes = [ctypes.c_void_p]
    cred_free.restype = None
    if not cred_read(target, 1, 0, ctypes.byref(credential_pointer)):
        error = ctypes.get_last_error()
        raise OSError(error, "Windows Credential Manager target could not be read")
    try:
        credential = credential_pointer.contents
        blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        if not blob:
            raise RuntimeError("Windows Credential Manager target contains an empty secret")
        encoding = "utf-16-le" if b"\x00" in blob else "utf-8"
        value = blob.decode(encoding).rstrip("\x00")
        if not value:
            raise RuntimeError("Windows Credential Manager target contains an empty secret")
        return value
    finally:
        cred_free(credential_pointer)


def resolve_credential_reference(reference, *, wincred_reader=None):
    target = parse_wincred_reference(reference)
    reader = wincred_reader or _read_windows_generic_credential
    return reader(target)


def load_global_credential_bundle(env=None, *, wincred_reader=None):
    env = env if env is not None else os.environ
    diagnostics = credential_diagnostics("polymarket_global", env=env)
    if not diagnostics["ok"]:
        raise RuntimeError(
            "International credentials must be complete storage references with no direct secret environment variables"
        )
    resolved = {
        field: resolve_credential_reference(env[name], wincred_reader=wincred_reader)
        for field, name in REFERENCE_ENV.items()
    }
    if not all(isinstance(value, str) and value for value in resolved.values()):
        raise RuntimeError("one or more credential references resolved to an empty secret")
    return GlobalCredentialBundle(
        **resolved,
        funder=str(env[FUNDER_ENV]).strip(),
    )


def credential_secret_hygiene(env=None):
    """Return secret-free evidence that only storage references were supplied."""

    diagnostics = credential_diagnostics(
        "polymarket_global",
        env=env if env is not None else os.environ,
    )
    return {
        "credentials_by_reference_verified": diagnostics.get("ok") is True,
        "direct_secret_environment_absent_verified": not bool(
            diagnostics.get("forbidden_direct_secret_env_names_present")
        ),
        "diagnostic_redaction_verified": diagnostics.get("values_redacted") is True,
        "required_reference_name_count": len(diagnostics.get("required_env_names") or []),
        "present_reference_name_count": len(diagnostics.get("present_env_names") or []),
    }


def stage0_client_identity_gate(stage0_identity, *, expected_funder=None, now=None):
    """Validate only the public facts required to construct a Stage 0 client."""

    identity = dict(stage0_identity or {})
    try:
        wallet_cap = float(identity.get("pilot_wallet_max_funding_usdc"))
    except (TypeError, ValueError):
        wallet_cap = None
    checks = {
        "exact_public_schema": set(identity) == STAGE0_IDENTITY_KEYS,
        "secret_material_absent": not contains_secret_material(identity),
        "schema": identity.get("schema_version") == STAGE0_IDENTITY_SCHEMA_VERSION,
        "authorization": identity.get("operator_authorization") == STAGE0_AUTHORIZATION,
        "platform": identity.get("platform") == "polymarket_global",
        "physical_geo_eligibility": international_jurisdiction(identity, now=now),
        "international_confirmed": identity.get("international_platform_confirmed") is True,
        "host": str(identity.get("clob_host") or "").rstrip("/").lower()
        == "https://clob.polymarket.com",
        "settlement_unit": identity.get("settlement_unit")
        == INTERNATIONAL_SETTLEMENT_UNIT,
        "chain": identity.get("chain_id") == 137,
        "sdk_distribution": identity.get("sdk_distribution") == OFFICIAL_CLOB_DISTRIBUTION,
        "sdk_version": identity.get("sdk_version") == OFFICIAL_CLOB_VERSION,
        "signature": signature_type_consistent(identity),
        "wallet_type": non_empty_text(identity.get("wallet_type")),
        "funder": valid_evm_address(identity.get("funder_address")),
        "expected_funder": (
            expected_funder is None
            or str(identity.get("funder_address") or "").lower()
            == str(expected_funder).lower()
        ),
        "isolated_wallet": identity.get("isolated_pilot_wallet") is True,
        "wallet_cap": wallet_cap is not None
        and math.isfinite(wallet_cap)
        and 0 < wallet_cap <= MAX_OPERATOR_PILOT_BUDGET_USDC,
    }
    missing = [name for name, passed in checks.items() if not passed]
    return {
        "ok": not missing,
        "checks": checks,
        "missing": missing,
        "platform": identity.get("platform"),
        "funder_address": identity.get("funder_address"),
        "signature_type": identity.get("signature_type"),
        "signature_type_id": identity.get("signature_type_id"),
        "pilot_wallet_max_funding_usdc": wallet_cap,
        "geographic_eligibility": identity.get("geographic_eligibility"),
        "identity": identity,
    }


def build_pinned_clob_client(
    credentials,
    stage0_identity,
    *,
    client_factory=None,
    api_creds_factory=None,
    now=None,
):
    """Construct the pinned client needed to collect the observed Stage 0 gate.

    The public identity manifest breaks the bootstrap dependency cycle but is
    not trading authorization.  Stage 1 still requires a passing observed
    ``mm_platform_bootstrap`` artifact.
    """

    identity_gate = stage0_client_identity_gate(
        stage0_identity,
        expected_funder=credentials.funder,
        now=now,
    )
    if not identity_gate["ok"]:
        raise RuntimeError(
            "Stage 0 client identity is invalid: " + ", ".join(identity_gate["missing"])
        )
    identity = identity_gate["identity"]
    signature_type_id = identity.get("signature_type_id")
    if signature_type_id not in {0, 1, 2, 3}:
        raise RuntimeError("Stage 0 client identity does not carry a supported signature type id")
    if client_factory is None or api_creds_factory is None:
        require_official_clob_version()
        from py_clob_client_v2 import ApiCreds, ClobClient

        client_factory = client_factory or ClobClient
        api_creds_factory = api_creds_factory or ApiCreds
    api_creds = api_creds_factory(
        api_key=credentials.api_key,
        api_secret=credentials.api_secret,
        api_passphrase=credentials.api_passphrase,
    )
    return client_factory(
        host="https://clob.polymarket.com",
        chain_id=137,
        key=credentials.private_key,
        creds=api_creds,
        signature_type=signature_type_id,
        funder=credentials.funder,
        use_server_time=True,
        retry_on_error=False,
    )
