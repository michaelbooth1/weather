"""One-time import of live-pilot secrets into Credential Manager.

The source file must remain outside the repository. Secret values are never
accepted as arguments, printed, or written to the public reference manifest or
receipt. The live trading commands continue to consume only ``wincred://``
references and a public funder address.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from weather.io import write_json_atomic
from weather.market.market_making_preflight import valid_evm_address
from weather.market.mm_credentials import (
    FUNDER_ENV,
    REFERENCE_ENV,
    delete_windows_generic_credential,
    windows_generic_credential_exists,
    write_windows_generic_credential,
)
from weather.paths import REPO_ROOT
from weather.schema_registry import schema_version


CONFIRMATION = "INTERNATIONAL_POLYMARKET_IMPORT_CREDENTIALS"
MANIFEST_SCHEMA_VERSION = schema_version("mm_live_credential_reference_manifest")
RECEIPT_SCHEMA_VERSION = schema_version("mm_live_credential_import_receipt")
MAX_SOURCE_BYTES = 65_536
SOURCE_SECRET_KEYS = {
    "api_key": "POLYMM_API_KEY",
    "api_secret": "POLYMM_API_SECRET",
    "api_passphrase": "POLYMM_API_PASSPHRASE",
    "private_key": "POLYMM_PRIVATE_KEY",
}
SOURCE_PUBLIC_KEYS = {
    "POLYMM_CLOB_HOST",
    "POLYMM_CHAIN_ID",
    "POLYMM_WALLET_ADDRESS",
    "POLYMM_FUNDER_ADDRESS",
    "POLYMM_SIGNATURE_TYPE",
}
IGNORED_SOURCE_KEYS = {
    "POLYMM_RELAYER_API_KEY",
    "POLYMM_RELAYER_API_KEY_ADDRESS",
    "POLYMM_POLYMARKET_VENUE",
    "POLYMM_LIVE_TRADING",
    "POLYMM_POLYGON_RPC_URL",
}
ALLOWED_SOURCE_KEYS = (
    set(SOURCE_SECRET_KEYS.values()) | SOURCE_PUBLIC_KEYS | IGNORED_SOURCE_KEYS
)
WINCRED_TARGETS = {
    "api_key": "Weather/Polymarket/InternationalPilot/ApiKey",
    "api_secret": "Weather/Polymarket/InternationalPilot/ApiSecret",
    "api_passphrase": "Weather/Polymarket/InternationalPilot/Passphrase",
    "private_key": "Weather/Polymarket/InternationalPilot/PrivateKey",
}
SIGNATURE_TOPOLOGIES = {
    "2": ("gnosis_safe", "POLY_GNOSIS_SAFE", 2),
    "POLY_GNOSIS_SAFE": ("gnosis_safe", "POLY_GNOSIS_SAFE", 2),
    "3": ("deposit_wallet", "POLY_1271", 3),
    "POLY_1271": ("deposit_wallet", "POLY_1271", 3),
}


class SourceCredentialBundle:
    __slots__ = (
        "api_key",
        "api_secret",
        "api_passphrase",
        "private_key",
        "wallet_address",
        "funder_address",
        "wallet_type",
        "signature_type",
        "signature_type_id",
    )

    def __init__(self, **values):
        for name in self.__slots__:
            setattr(self, name, values[name])

    def __repr__(self):
        return (
            "SourceCredentialBundle(api_key=<redacted>, api_secret=<redacted>, "
            "api_passphrase=<redacted>, private_key=<redacted>, "
            "wallet_address=<public>, funder_address=<public>)"
        )


class CredentialSourceValidationError(RuntimeError):
    def __init__(self, checks, missing):
        self.checks = dict(checks)
        self.missing = list(missing)
        super().__init__(
            "credential source failed validation: " + ", ".join(self.missing)
        )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    attributes = getattr(path.stat(), "st_file_attributes", 0)
    return bool(attributes & 0x400)


def _new_external_paths(source_path, manifest_path, receipt_path, *, repo_root):
    source_input = Path(source_path)
    if _is_reparse_point(source_input):
        raise RuntimeError("credential source must not be a symlink or reparse point")
    source = source_input.resolve(strict=True)
    manifest = Path(manifest_path).resolve()
    receipt = Path(receipt_path).resolve()
    root = Path(repo_root).resolve()
    if not source.is_file():
        raise RuntimeError("credential source must be a regular file")
    if source.stat().st_size <= 0 or source.stat().st_size > MAX_SOURCE_BYTES:
        raise RuntimeError("credential source size is outside the accepted bound")
    if any(_is_within(path, root) for path in (source, manifest, receipt)):
        raise RuntimeError("credential source and outputs must remain outside the repository")
    if len({source, manifest, receipt}) != 3:
        raise RuntimeError("credential source, manifest, and receipt paths must be distinct")
    if manifest.exists() or receipt.exists():
        raise RuntimeError("credential import output paths must be new")
    for parent in {manifest.parent, receipt.parent}:
        parent.mkdir(parents=True, exist_ok=True)
    return source, manifest, receipt


def _parse_source(path: Path) -> dict:
    values = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RuntimeError("credential source contains a malformed line")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in values:
            raise RuntimeError("credential source contains a missing or duplicate key")
        if key not in ALLOWED_SOURCE_KEYS:
            raise RuntimeError("credential source contains an unknown key")
        if not value or "\x00" in value:
            raise RuntimeError("credential source contains an empty or invalid value")
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            raise RuntimeError("credential source values must not include shell quotes")
        values[key] = value
    required = set(SOURCE_SECRET_KEYS.values()) | SOURCE_PUBLIC_KEYS
    if not required.issubset(values):
        raise RuntimeError("credential source is missing a required key")
    return values


def _derive_account_address(private_key):
    from eth_account import Account

    return Account.from_key(private_key).address


def _validated_bundle(values, *, account_deriver):
    signature_value = str(values["POLYMM_SIGNATURE_TYPE"]).strip().upper()
    topology = SIGNATURE_TOPOLOGIES.get(signature_value)
    wallet_address = values["POLYMM_WALLET_ADDRESS"].strip()
    funder_address = values["POLYMM_FUNDER_ADDRESS"].strip()
    api_values = [values[name] for name in SOURCE_SECRET_KEYS.values() if name != "POLYMM_PRIVATE_KEY"]
    checks = {
        "clob_host_exact": values["POLYMM_CLOB_HOST"].rstrip("/").lower()
        == "https://clob.polymarket.com",
        "chain_id_exact": values["POLYMM_CHAIN_ID"].strip() == "137",
        "signature_topology_supported": topology is not None,
        "wallet_address_valid": valid_evm_address(wallet_address),
        "funder_address_valid": valid_evm_address(funder_address),
        "wallet_and_funder_distinct": wallet_address.lower()
        != funder_address.lower(),
        "api_credentials_have_no_whitespace": all(
            value and not any(character.isspace() for character in value)
            for value in api_values
        ),
    }
    derived_address = None
    try:
        derived_address = str(account_deriver(values["POLYMM_PRIVATE_KEY"]))
    except Exception:
        pass
    checks["private_key_parseable"] = valid_evm_address(derived_address)
    checks["private_key_matches_wallet_address"] = (
        valid_evm_address(derived_address)
        and derived_address.lower() == wallet_address.lower()
    )
    missing = [name for name, passed in checks.items() if not passed]
    if missing:
        raise CredentialSourceValidationError(checks, missing)
    wallet_type, signature_type, signature_type_id = topology
    return SourceCredentialBundle(
        api_key=values["POLYMM_API_KEY"],
        api_secret=values["POLYMM_API_SECRET"],
        api_passphrase=values["POLYMM_API_PASSPHRASE"],
        private_key=values["POLYMM_PRIVATE_KEY"],
        wallet_address=wallet_address,
        funder_address=funder_address,
        wallet_type=wallet_type,
        signature_type=signature_type,
        signature_type_id=signature_type_id,
    ), checks


def import_live_pilot_credentials(
    source_path,
    manifest_path,
    receipt_path,
    *,
    confirmation,
    source_acl_private_confirmed,
    repo_root=REPO_ROOT,
    platform_name=os.name,
    account_deriver=_derive_account_address,
    credential_exists=windows_generic_credential_exists,
    credential_writer=write_windows_generic_credential,
    credential_deleter=delete_windows_generic_credential,
):
    """Validate and atomically import four secrets into new fixed targets."""

    if confirmation != CONFIRMATION:
        raise RuntimeError("credential import requires the exact confirmation token")
    if not source_acl_private_confirmed:
        raise RuntimeError("credential import requires private source ACL confirmation")
    source, manifest_out, receipt_out = _new_external_paths(
        source_path,
        manifest_path,
        receipt_path,
        repo_root=repo_root,
    )
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "FAIL",
        "platform": "polymarket_global",
        "source_outside_repository_verified": True,
        "source_acl_private_confirmed": True,
        "credential_value_count_expected": len(WINCRED_TARGETS),
        "credential_value_count_written": 0,
        "credential_values_retained": False,
        "ignored_source_key_count": 0,
        "checks": {},
        "missing": [],
        "rollback_attempted": False,
        "rollback_ok": None,
        "source_deletion_required_after_transfer": True,
    }
    created_targets = []
    operation_error = None
    manifest = None
    try:
        if platform_name != "nt":
            raise RuntimeError("credential import is supported only on Windows")
        values = _parse_source(source)
        bundle, checks = _validated_bundle(
            values,
            account_deriver=account_deriver,
        )
        receipt["checks"] = checks
        receipt["ignored_source_key_count"] = len(
            set(values).intersection(IGNORED_SOURCE_KEYS)
        )
        existing = [
            field for field, target in WINCRED_TARGETS.items()
            if credential_exists(target)
        ]
        if existing:
            receipt["missing"] = ["fixed_credential_targets_are_new"]
            raise RuntimeError("one or more fixed credential targets already exist")
        for field, target in WINCRED_TARGETS.items():
            credential_writer(target, getattr(bundle, field))
            created_targets.append(target)
        receipt["credential_value_count_written"] = len(created_targets)
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "platform": "polymarket_global",
            "wallet_type": bundle.wallet_type,
            "signature_type": bundle.signature_type,
            "signature_type_id": bundle.signature_type_id,
            "wallet_address": bundle.wallet_address,
            "funder_address": bundle.funder_address,
            "credential_references": {
                REFERENCE_ENV[field]: f"wincred://{target}"
                for field, target in WINCRED_TARGETS.items()
            },
            "public_environment": {
                FUNDER_ENV: bundle.funder_address,
            },
            "secret_values_retained": False,
            "ignored_relayers_rpc_and_self_assertions": True,
        }
        write_json_atomic(manifest_out, manifest, trailing_newline=True)
        receipt["status"] = "PASS"
    except Exception as exc:
        if isinstance(exc, CredentialSourceValidationError):
            receipt["checks"] = exc.checks
            receipt["missing"] = exc.missing
        operation_error = exc
    if operation_error is not None and created_targets:
        receipt["rollback_attempted"] = True
        rollback_ok = True
        for target in reversed(created_targets):
            try:
                credential_deleter(target)
            except Exception:
                rollback_ok = False
        receipt["rollback_ok"] = rollback_ok
        receipt["credential_value_count_written"] = 0 if rollback_ok else len(created_targets)
        try:
            if manifest_out.exists():
                manifest_out.unlink()
        except OSError:
            rollback_ok = False
            receipt["rollback_ok"] = False
    if operation_error is not None:
        receipt["exception_type"] = type(operation_error).__name__
    try:
        write_json_atomic(receipt_out, receipt, trailing_newline=True)
    except Exception:
        if created_targets and not receipt["rollback_attempted"]:
            for target in reversed(created_targets):
                try:
                    credential_deleter(target)
                except Exception:
                    pass
        try:
            if manifest_out.exists():
                manifest_out.unlink()
        except OSError:
            pass
        raise
    if operation_error is not None:
        raise operation_error
    return {"manifest": manifest, "receipt": receipt}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-env", required=True)
    parser.add_argument("--manifest-out", required=True)
    parser.add_argument("--receipt-out", required=True)
    parser.add_argument("--confirm-source-acl-private", action="store_true")
    parser.add_argument("--confirmation", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = import_live_pilot_credentials(
            args.source_env,
            args.manifest_out,
            args.receipt_out,
            confirmation=args.confirmation,
            source_acl_private_confirmed=args.confirm_source_acl_private,
        )
    except Exception as exc:
        print(f"credential import failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(
        "credential import PASS: "
        f"{result['receipt']['credential_value_count_written']} entries"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
