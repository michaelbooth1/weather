"""Credential-by-reference loading for the International live probe.

Only Windows Credential Manager generic credentials are supported on the
production host. References identify vault entries; secret values must never
be supplied directly through environment variables or command arguments.
"""

from __future__ import annotations

import ctypes

import os
from ctypes import wintypes
from urllib.parse import unquote, urlsplit

from weather.market.mm_exchange import credential_diagnostics
from weather.market.mm_pilot_capital import (
    ALLOCATION_KEYS, capital_declaration, pilot_capital_limit,
)
from weather.market.mm_official_adapter import (
    OFFICIAL_CLOB_DISTRIBUTION,
    OFFICIAL_CLOB_VERSION,
    require_official_clob_version,
)
from weather.market.mm_official_transport import fetch_wallet_deployed
from weather.market.market_making_preflight import (
    INTERNATIONAL_SETTLEMENT_UNIT,
    contains_secret_material,
    pilot_wallet_signature_topology,
    valid_evm_address,
)
from weather.market.market_making_run_constants import MAX_OPERATOR_PILOT_BUDGET_USDC


REFERENCE_ENV = {
    "api_key": "POLYMARKET_API_KEY_STORAGE_REF",
    "api_secret": "POLYMARKET_API_SECRET_STORAGE_REF",
    "api_passphrase": "POLYMARKET_API_PASSPHRASE_STORAGE_REF",
    "private_key": "POLYMARKET_PRIVATE_KEY_STORAGE_REF",
}
FUNDER_ENV = "POLYMARKET_FUNDER_ADDRESS"
WINCRED_SCHEME = "wincred"
STAGE0_IDENTITY_SCHEMA_VERSION = "mm_stage0_client_identity_v0.4"
STAGE0_AUTHORIZATION = (
    "INTERNATIONAL_POLYMARKET_STAGE0_HEARTBEAT_AND_ACCOUNT_WIDE_CANCEL_ALL_NO_ORDER"
)
STAGE0_IDENTITY_KEYS = {
    "schema_version",
    "operator_authorization",
    "platform",
    "international_platform_confirmed",
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


def windows_generic_credential_exists(target):
    """Check a Generic Credential target without copying its secret blob."""

    if os.name != "nt":
        raise RuntimeError("Windows Credential Manager is supported only on Windows")

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("unused", ctypes.c_byte)]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    pointer = ctypes.POINTER(CREDENTIAL)()
    cred_read = advapi32.CredReadW
    cred_read.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    cred_read.restype = wintypes.BOOL
    cred_free = advapi32.CredFree
    cred_free.argtypes = [ctypes.c_void_p]
    cred_free.restype = None
    if cred_read(str(target), 1, 0, ctypes.byref(pointer)):
        cred_free(pointer)
        return True
    error = ctypes.get_last_error()
    if error == 1168:  # ERROR_NOT_FOUND
        return False
    raise OSError(error, "Windows Credential Manager target could not be checked")


def write_windows_generic_credential(target, value):
    """Write a new current-user Generic Credential without command-line secrets."""

    if os.name != "nt":
        raise RuntimeError("Windows Credential Manager is supported only on Windows")
    target = str(target or "").strip()
    if not target:
        raise ValueError("credential target is required")
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("credential value must be a nonempty NUL-free string")
    encoded = value.encode("utf-8")
    if len(encoded) > 5120:
        raise ValueError("credential value exceeds the Generic Credential limit")

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

    buffer = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
    credential = CREDENTIAL()
    credential.Type = 1  # CRED_TYPE_GENERIC
    credential.TargetName = target
    credential.Comment = "Weather International live-pilot credential"
    credential.CredentialBlobSize = len(encoded)
    credential.CredentialBlob = ctypes.cast(
        buffer,
        ctypes.POINTER(ctypes.c_ubyte),
    )
    credential.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE, current-user scoped
    credential.UserName = "weather-live-pilot"
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    cred_write = advapi32.CredWriteW
    cred_write.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    cred_write.restype = wintypes.BOOL
    if not cred_write(ctypes.byref(credential), 0):
        error = ctypes.get_last_error()
        raise OSError(error, "Windows Credential Manager target could not be written")


def delete_windows_generic_credential(target):
    """Delete one exact Generic Credential target."""

    if os.name != "nt":
        raise RuntimeError("Windows Credential Manager is supported only on Windows")
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    cred_delete = advapi32.CredDeleteW
    cred_delete.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    cred_delete.restype = wintypes.BOOL
    if not cred_delete(str(target), 1, 0):
        error = ctypes.get_last_error()
        if error != 1168:
            raise OSError(error, "Windows Credential Manager target could not be deleted")


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
        wallet_cap = float(pilot_capital_limit(identity, require_wallet_declaration=True))
    except (TypeError, ValueError):
        wallet_cap = None
    checks = {
        "exact_public_schema": set(identity) in (
            STAGE0_IDENTITY_KEYS, STAGE0_IDENTITY_KEYS | ALLOCATION_KEYS
        ),
        "secret_material_absent": not contains_secret_material(identity),
        "schema": identity.get("schema_version") == STAGE0_IDENTITY_SCHEMA_VERSION,
        "authorization": identity.get("operator_authorization") == STAGE0_AUTHORIZATION,
        "platform": identity.get("platform") == "polymarket_global",
        "international_confirmed": identity.get("international_platform_confirmed") is True,
        "host": str(identity.get("clob_host") or "").rstrip("/").lower()
        == "https://clob.polymarket.com",
        "settlement_unit": identity.get("settlement_unit")
        == INTERNATIONAL_SETTLEMENT_UNIT,
        "chain": identity.get("chain_id") == 137,
        "sdk_distribution": identity.get("sdk_distribution") == OFFICIAL_CLOB_DISTRIBUTION,
        "sdk_version": identity.get("sdk_version") == OFFICIAL_CLOB_VERSION,
        "pilot_wallet_signature_topology": pilot_wallet_signature_topology(
            identity
        ),
        "funder": valid_evm_address(identity.get("funder_address")),
        "expected_funder": (
            expected_funder is None
            or str(identity.get("funder_address") or "").lower()
            == str(expected_funder).lower()
        ),
        "capital_contract": wallet_cap is not None,
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
        **capital_declaration(identity),
        "pilot_capital_limit_pusd": wallet_cap,
        "identity": identity,
    }


def build_unified_clob_client(
    credentials,
    stage0_identity,
    *,
    client_factory=None,
    api_creds_factory=None,
    wallet_deployed_reader=None,
    expected_signer_address=None,
    account_deriver=None,
    now=None,
):
    """Construct the pinned unified client after a no-deploy preflight.

    The public identity manifest breaks the bootstrap dependency cycle but is
    not trading authorization.  Stage 1 still requires a passing observed
    ``mm_platform_bootstrap`` artifact.  ``SecureClient.create`` can deploy a
    missing default deposit wallet, so the public relayer proof must pass
    before client construction is allowed.
    """

    expected_signer = str(expected_signer_address or "").lower()
    if not valid_evm_address(expected_signer):
        raise RuntimeError("Stage 0 requires the sealed public signer address")
    if account_deriver is None:
        from eth_account import Account

        def account_deriver(key):
            return Account.from_key(key).address
    try:
        derived_signer = str(account_deriver(credentials.private_key)).lower()
    except Exception as exc:
        raise RuntimeError("current private signer could not be derived") from exc
    if derived_signer != expected_signer:
        raise RuntimeError("current private signer differs from the sealed manifest")
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
    if signature_type_id not in {2, 3}:
        raise RuntimeError("Stage 0 requires a supported Safe or deposit-wallet signature type")
    deployment_reader = wallet_deployed_reader or fetch_wallet_deployed
    if deployment_reader(credentials.funder, signature_type_id) is not True:
        raise RuntimeError(
            "Stage 0 refuses client construction until the existing wallet is proven deployed"
        )
    if client_factory is None or api_creds_factory is None:
        require_official_clob_version()
        from polymarket import ApiKeyCreds, SecureClient

        client_factory = client_factory or SecureClient.create
        api_creds_factory = api_creds_factory or ApiKeyCreds
    api_creds = api_creds_factory(
        key=credentials.api_key,
        secret=credentials.api_secret,
        passphrase=credentials.api_passphrase,
    )
    client = client_factory(
        private_key=credentials.private_key,
        wallet=credentials.funder,
        credentials=api_creds,
    )
    expected_wallet_type = {2: "GNOSIS_SAFE", 3: "DEPOSIT_WALLET"}[signature_type_id]
    observed_wallet = str(getattr(client, "wallet", "") or "").lower()
    observed_signer = str(getattr(client, "signer", "") or "").lower()
    observed_wallet_type = str(getattr(client, "wallet_type", "") or "").upper()
    topology_valid = all((
        observed_wallet == str(credentials.funder).lower(),
        valid_evm_address(observed_wallet),
        valid_evm_address(observed_signer),
        observed_signer != observed_wallet,
        observed_signer == expected_signer == derived_signer,
        observed_wallet_type == expected_wallet_type,
    ))
    if not topology_valid:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
        raise RuntimeError("unified client returned an unexpected signer/wallet topology")
    return client
