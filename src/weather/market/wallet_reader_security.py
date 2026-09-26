"""Credential selection and output guard for the owner-started wallet reader.

The loader follows RE-1's in-memory, non-interpolating dotenv pattern without
importing RE-1's trading dependency graph. Importing this module reads nothing.
"""
from __future__ import annotations

import base64
import contextlib
import io
import ipaddress
import json
import logging
from pathlib import Path
import re
import subprocess

from weather.operations.live_path_security import validate_regular_nonreparse_file
from weather.paths import REPO_ROOT

CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
FIELDS = ("API_KEY", "API_SECRET", "API_PASSPHRASE", "WALLET_ADDRESS",
          "FUNDER_ADDRESS", "CLOB_HOST", "CHAIN_ID", "READER_TOKEN")
ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")
CONDITION = re.compile(r"0x[0-9a-fA-F]{64}\Z")
RFC1918 = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


class ReaderError(RuntimeError):
    """Only fixed, credential-free error codes cross the reader boundary."""


class SecretGuard:
    """RE-1 SecretGuard semantics: remove auth fields; refuse residual secrets.

Kept independent of the unmerged RE-1 order-execution modules. Also removes
reader tokens and normalized POLY header names, including other users' keys.
"""
    def __init__(self, secrets=()):
        self.secrets = tuple(s for s in secrets if s)

    def clean(self, value):
        if isinstance(value, dict):
            value = {k: self.clean(v) for k, v in value.items()
                     if not any(part in re.sub("[^a-z]", "", str(k).lower())
                                for part in ("header", "auth", "signature", "secret", "apikey",
                                             "passphrase", "privatekey", "readertoken", "credential"))
                     and str(k).lower() != "owner"}
        elif isinstance(value, (tuple, list)):
            value = [self.clean(v) for v in value]
        encoded = json.dumps(value, ensure_ascii=True, allow_nan=False)
        if any(s in encoded or json.dumps(s)[1:-1] in encoded for s in self.secrets):
            raise ReaderError("secret_output_refused")
        return value


def common_repository_root():
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True, check=True, timeout=10)
    return Path(result.stdout.strip()).parent


def load_owner_credentials():
    """Called only by owner-started serve; tests substitute the common root.

dotenv necessarily parses the file into a mapping. Only FIELDS are selected;
no other entry is inspected, interpolated, exported, retained, or used.
"""
    from dotenv import dotenv_values

    logger = logging.getLogger("dotenv.main")
    was_disabled = logger.disabled
    values = None
    try:
        path = validate_regular_nonreparse_file(common_repository_root() / ".env")
        logger.disabled = True
        with contextlib.redirect_stderr(io.StringIO()):
            values = dotenv_values(path, interpolate=False)
        fields = {key: values.get("POLYMM_" + key) for key in FIELDS}
    except Exception:
        raise ReaderError("credential_file_unreadable") from None
    finally:
        if values is not None:
            values.clear()
        logger.disabled = was_disabled
    if any(not isinstance(v, str) or not v or any(ord(c) < 32 for c in v)
           for v in fields.values()):
        raise ReaderError("credential_fields_missing_or_invalid")
    if fields["CLOB_HOST"] != CLOB or fields["CHAIN_ID"] != "137":
        raise ReaderError("credential_topology_refused")
    if any(not ADDRESS.fullmatch(fields[k]) for k in ("WALLET_ADDRESS", "FUNDER_ADDRESS")):
        raise ReaderError("wallet_address_invalid")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", fields["READER_TOKEN"]):
        raise ReaderError("reader_token_must_be_32_bytes_hex")
    try:
        if not base64.b64decode(fields["API_SECRET"], altchars=b"-_", validate=True):
            raise ValueError
    except ValueError:
        raise ReaderError("api_secret_encoding_invalid") from None
    guard = SecretGuard(fields[k] for k in ("API_KEY", "API_SECRET", "API_PASSPHRASE", "READER_TOKEN"))
    return fields, guard


def lan_ip(value):
    try:
        address = ipaddress.IPv4Address(value)
        if str(address) != value or not any(address in network for network in RFC1918):
            raise ValueError
    except (ValueError, TypeError):
        raise ReaderError("rfc1918_ipv4_required") from None
    return value
