"""Create or exactly verify live-pilot secrets in Credential Manager.

The source file must remain outside the repository. Secret values are never
accepted as arguments, printed, or written to the public reference manifest or
receipt. The live trading commands continue to consume only ``wincred://``
references and a public funder address.

The CLI activates the already sealed, hash-pinned process-local live SDK
overlay before deriving the signer. The shared production environment remains
unchanged and is not expected to contain the live SDK dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from weather.execution_host import (
    current_execution_host_id,
    current_execution_principal_id,
)
from weather.market.market_making_preflight import valid_evm_address
from weather.market.mm_credentials import (
    FUNDER_ENV,
    REFERENCE_ENV,
    delete_windows_generic_credential,
    resolve_credential_reference,
    windows_generic_credential_exists,
    write_windows_generic_credential,
)
from weather.paths import REPO_ROOT
from weather.operations.live_path_security import (
    validate_nonreparse_directory,
    validate_regular_nonreparse_file,
)
from weather.schema_registry import schema_version


CONFIRMATION = "INTERNATIONAL_POLYMARKET_IMPORT_CREDENTIALS"
VERIFY_EXISTING_EXACT_CONFIRMATION = (
    "INTERNATIONAL_POLYMARKET_VERIFY_EXISTING_EXACT_CREDENTIALS"
)
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
ALLOWED_SOURCE_KEYS = set(SOURCE_SECRET_KEYS.values()) | SOURCE_PUBLIC_KEYS
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

WINDOWS_RESERVATION_SHARE_MODE = 0  # exclusive until publication or disposition


def _open_create_only_descriptor(path: Path, flags: int, mode: int = 0o600) -> int:
    if os.name != "nt":
        return os.open(path, flags, mode)

    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    desired_access = 0x80000000 | 0x40000000 | 0x00010000
    handle = create_file(
        str(path),
        desired_access,
        WINDOWS_RESERVATION_SHARE_MODE,
        None,
        1,  # CREATE_NEW
        0x00000080,  # FILE_ATTRIBUTE_NORMAL
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        error = ctypes.get_last_error()
        if error in {80, 183}:  # ERROR_FILE_EXISTS / ERROR_ALREADY_EXISTS
            raise FileExistsError(error, f"output path already exists: {path}")
        raise ctypes.WinError(error)
    try:
        descriptor = msvcrt.open_osfhandle(
            int(handle),
            os.O_RDWR
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOINHERIT", 0),
        )
    except BaseException:
        close_handle(handle)
        raise
    try:
        os.set_inheritable(descriptor, False)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _delete_windows_descriptor(descriptor: int) -> bool:
    if os.name != "nt":
        return False

    import ctypes
    import msvcrt
    from ctypes import wintypes

    class FileDispositionInfo(ctypes.Structure):
        _fields_ = [("delete_file", ctypes.c_ubyte)]

    set_information = ctypes.WinDLL(
        "kernel32", use_last_error=True
    ).SetFileInformationByHandle
    set_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    set_information.restype = wintypes.BOOL
    disposition = FileDispositionInfo(1)
    return bool(
        set_information(
            wintypes.HANDLE(msvcrt.get_osfhandle(descriptor)),
            4,  # FileDispositionInfo
            ctypes.byref(disposition),
            ctypes.sizeof(disposition),
        )
    )


def _windows_handle_information(handle: int) -> tuple[tuple[int, int, int], int]:
    import ctypes
    from ctypes import wintypes

    class FileTime(ctypes.Structure):
        _fields_ = (
            ("low", wintypes.DWORD),
            ("high", wintypes.DWORD),
        )

    class ByHandleFileInformation(ctypes.Structure):
        _fields_ = (
            ("attributes", wintypes.DWORD),
            ("creation_time", FileTime),
            ("last_access_time", FileTime),
            ("last_write_time", FileTime),
            ("volume_serial_number", wintypes.DWORD),
            ("file_size_high", wintypes.DWORD),
            ("file_size_low", wintypes.DWORD),
            ("number_of_links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        )

    get_information = ctypes.WinDLL(
        "kernel32", use_last_error=True
    ).GetFileInformationByHandle
    get_information.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(ByHandleFileInformation),
    )
    get_information.restype = wintypes.BOOL
    information = ByHandleFileInformation()
    if not get_information(wintypes.HANDLE(handle), ctypes.byref(information)):
        raise ctypes.WinError(ctypes.get_last_error())
    identity = (
        int(information.volume_serial_number),
        int(information.file_index_high),
        int(information.file_index_low),
    )
    size = (int(information.file_size_high) << 32) | int(
        information.file_size_low
    )
    return identity, size


def _windows_descriptor_information(
    descriptor: int,
) -> tuple[tuple[int, int, int], int]:
    import msvcrt

    return _windows_handle_information(msvcrt.get_osfhandle(descriptor))


def _windows_path_information(path: Path) -> tuple[tuple[int, int, int], int]:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    handle = create_file(
        str(path),
        0,  # metadata query without read/write/delete access
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        3,  # OPEN_EXISTING
        0x00200000,  # FILE_FLAG_OPEN_REPARSE_POINT
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        error = ctypes.get_last_error()
        if error in {2, 3}:  # ERROR_FILE_NOT_FOUND / ERROR_PATH_NOT_FOUND
            raise FileNotFoundError(error, f"output path disappeared: {path}")
        raise ctypes.WinError(error)
    try:
        return _windows_handle_information(int(handle))
    finally:
        close_handle(handle)


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


class CredentialValidationDependencyError(RuntimeError):
    """Raised when the sealed offline validator is not available."""


class _CreateOnlyOutput:
    """Own one new output file identity from reservation through publication.

    Credential import rejects real non-Windows operation before reservation.
    The POSIX cleanup path exists for deterministic cross-platform simulation;
    it preserves uncertain objects in a caller-visible quarantine instead of
    performing a pathname unlink without handle-bound ownership.
    """

    def __init__(self, path: Path, *, label: str):
        self.path = path
        self.label = label
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        try:
            descriptor = _open_create_only_descriptor(
                self.path,
                flags,
                0o600,
            )
        except FileExistsError as exc:
            raise RuntimeError(f"{label} output path must be new") from exc
        try:
            identity = os.fstat(descriptor)
            windows_identity = (
                _windows_descriptor_information(descriptor)[0]
                if os.name == "nt"
                else None
            )
        except BaseException:
            os.close(descriptor)
            raise
        self._descriptor = descriptor
        self._identity = identity
        self._windows_identity = windows_identity
        self._expected_sha256 = None
        self._owned_sha256 = hashlib.sha256(b"").hexdigest()
        self.quarantine_path: Path | None = None

    def write_json(self, payload) -> None:
        raw = (json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n").encode(
            "utf-8"
        )
        descriptor = self._require_open()
        view = memoryview(raw)
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.ftruncate(descriptor, 0)
            offset = 0
            while offset < len(view):
                written = os.write(descriptor, view[offset:])
                if written <= 0:
                    raise OSError(f"{self.label} publication made no progress")
                offset += written
            os.fsync(descriptor)
        finally:
            view.release()
        self._expected_sha256 = hashlib.sha256(raw).hexdigest()
        self._owned_sha256 = self._expected_sha256
        self._identity = os.fstat(descriptor)

    def verify(self) -> None:
        descriptor = self._require_open()
        try:
            if os.name == "nt":
                descriptor_identity, _descriptor_size = (
                    _windows_descriptor_information(descriptor)
                )
                observed_identity, _observed_size = _windows_path_information(
                    self.path
                )
                same_identity = (
                    self._windows_identity
                    == descriptor_identity
                    == observed_identity
                )
            else:
                observed_identity = self.path.stat()
                same_identity = os.path.samestat(self._identity, observed_identity)
        except OSError as exc:
            raise RuntimeError(f"{self.label} publication path disappeared") from exc
        if not same_identity:
            raise RuntimeError(f"{self.label} publication ownership changed")
        if self._expected_sha256 is None:
            raise RuntimeError(f"{self.label} publication was not written")
        os.lseek(descriptor, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
        if digest.hexdigest() != self._expected_sha256:
            raise RuntimeError(f"{self.label} publication changed")

    def close(self) -> None:
        descriptor = self._descriptor
        self._descriptor = None
        if descriptor is not None:
            os.close(descriptor)

    def remove_if_owned(self) -> bool:
        descriptor = self._descriptor
        if descriptor is None:
            # Once the reservation handle is closed, a recycled filesystem
            # identity cannot prove that the current path is still ours.
            return False
        try:
            try:
                descriptor_identity = os.fstat(descriptor)
                if os.name == "nt":
                    descriptor_windows_identity, descriptor_windows_size = (
                        _windows_descriptor_information(descriptor)
                    )
                    descriptor_sha256 = self._descriptor_sha256(descriptor)
                    if not (
                        os.path.samestat(self._identity, descriptor_identity)
                        and self._windows_identity == descriptor_windows_identity
                        and descriptor_identity.st_size == descriptor_windows_size
                        and descriptor_sha256 == self._owned_sha256
                    ):
                        return False
                    return _delete_windows_descriptor(descriptor)

                observed_identity = self.path.lstat()
                descriptor_sha256 = self._descriptor_sha256(descriptor)
            except FileNotFoundError:
                return True
            except OSError:
                return False
            if not (
                os.path.samestat(self._identity, descriptor_identity)
                and os.path.samestat(descriptor_identity, observed_identity)
                and descriptor_identity.st_size == observed_identity.st_size
                and descriptor_sha256 == self._owned_sha256
            ):
                return False

            try:
                quarantine_root = Path(
                    tempfile.mkdtemp(
                        prefix=f".{self.path.name}.cleanup-",
                        dir=self.path.parent,
                    )
                )
            except OSError:
                return False
            quarantined = quarantine_root / self.path.name
            try:
                os.rename(self.path, quarantined)
            except FileNotFoundError:
                try:
                    quarantine_root.rmdir()
                except OSError:
                    pass
                return True
            except OSError:
                try:
                    quarantine_root.rmdir()
                except OSError:
                    pass
                return False
            self.quarantine_path = quarantined
            try:
                quarantined_identity = quarantined.lstat()
                owned = (
                    stat.S_ISREG(quarantined_identity.st_mode)
                    and os.path.samestat(descriptor_identity, quarantined_identity)
                    and descriptor_identity.st_size == quarantined_identity.st_size
                    and self._path_sha256(quarantined) == self._owned_sha256
                )
                if not owned:
                    self._restore_quarantined_replacement(quarantined)
                    return False
                return True
            except OSError:
                return False
        finally:
            self.close()

    @staticmethod
    def _path_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _descriptor_sha256(descriptor: int) -> str:
        position = os.lseek(descriptor, 0, os.SEEK_CUR)
        digest = hashlib.sha256()
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            while block := os.read(descriptor, 1024 * 1024):
                digest.update(block)
        finally:
            os.lseek(descriptor, position, os.SEEK_SET)
        return digest.hexdigest()

    def _restore_quarantined_replacement(self, quarantined: Path) -> bool:
        try:
            if not stat.S_ISREG(quarantined.lstat().st_mode):
                return False
            os.link(quarantined, self.path)
        except OSError:
            return False
        return True

    def _require_open(self) -> int:
        if self._descriptor is None:
            raise RuntimeError(f"{self.label} reservation is closed")
        return self._descriptor


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _new_external_paths(source_path, manifest_path, receipt_path, *, repo_root):
    source = validate_regular_nonreparse_file(source_path)
    manifest_input = Path(os.path.abspath(os.fspath(manifest_path)))
    receipt_input = Path(os.path.abspath(os.fspath(receipt_path)))
    root = Path(repo_root).resolve()
    if any(
        _is_within(path.resolve(strict=False), root)
        for path in (source, manifest_input, receipt_input)
    ):
        raise RuntimeError("credential source and outputs must remain outside the repository")
    if len({source, manifest_input, receipt_input}) != 3:
        raise RuntimeError("credential source, manifest, and receipt paths must be distinct")
    for parent in {manifest_input.parent, receipt_input.parent}:
        parent.mkdir(parents=True, exist_ok=True)
        validate_nonreparse_directory(parent)
    manifest = manifest_input.parent.resolve(strict=True) / manifest_input.name
    receipt = receipt_input.parent.resolve(strict=True) / receipt_input.name
    return source, manifest, receipt


def _read_source_snapshot(path: Path) -> bytes:
    """Read one bounded source generation through a retained file descriptor."""

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise RuntimeError("credential source must be a regular file")
        if opened.st_size <= 0 or opened.st_size > MAX_SOURCE_BYTES:
            raise RuntimeError("credential source size is outside the accepted bound")
        try:
            before = path.stat()
        except OSError as exc:
            raise RuntimeError("credential source disappeared before reading") from exc
        if not os.path.samestat(opened, before):
            raise RuntimeError("credential source identity changed before reading")
        chunks = []
        total = 0
        while True:
            block = os.read(descriptor, min(8192, MAX_SOURCE_BYTES + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
            if total > MAX_SOURCE_BYTES:
                raise RuntimeError("credential source size is outside the accepted bound")
        after_handle = os.fstat(descriptor)
        try:
            after_path = path.stat()
        except OSError as exc:
            raise RuntimeError("credential source disappeared while reading") from exc
        if (
            not os.path.samestat(opened, after_handle)
            or not os.path.samestat(opened, after_path)
            or after_handle.st_size != total
            or after_handle.st_mtime_ns != opened.st_mtime_ns
        ):
            raise RuntimeError("credential source identity or bytes changed while reading")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _parse_source(raw: bytes) -> dict:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RuntimeError("credential source must be strict UTF-8 text") from exc
    values = {}
    for raw_line in text.splitlines():
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
    if set(values) != required:
        raise RuntimeError("credential source must contain exactly the required keys")
    return values


def _derive_account_address(private_key):
    try:
        from eth_account import Account

        return Account.from_key(private_key).address
    except ImportError as exc:
        raise CredentialValidationDependencyError(
            "sealed private-key validator dependency is unavailable"
        ) from exc


def _read_windows_generic_credential_by_target(target):
    return resolve_credential_reference(f"wincred://{target}")


def _secret_values_match(actual, expected):
    if not isinstance(actual, str) or not isinstance(expected, str):
        return False
    try:
        actual_bytes = actual.encode("utf-8")
        expected_bytes = expected.encode("utf-8")
    except UnicodeError:
        return False
    return hmac.compare_digest(actual_bytes, expected_bytes)


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
    except CredentialValidationDependencyError:
        raise
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
    credential_reader=_read_windows_generic_credential_by_target,
    credential_writer=write_windows_generic_credential,
    credential_deleter=delete_windows_generic_credential,
    verify_existing_exact=False,
    clock=lambda: datetime.now(timezone.utc),
    execution_host_id_provider=current_execution_host_id,
    execution_principal_id_provider=current_execution_principal_id,
):
    """Create four fixed credentials or verify that all four already match."""

    expected_confirmation = (
        VERIFY_EXISTING_EXACT_CONFIRMATION
        if verify_existing_exact
        else CONFIRMATION
    )
    if confirmation != expected_confirmation:
        raise RuntimeError("credential preparation requires the exact confirmation token")
    if not source_acl_private_confirmed:
        raise RuntimeError("credential import requires private source ACL confirmation")
    if platform_name != "nt":
        raise RuntimeError("credential import is supported only on Windows")
    source, manifest_out, receipt_out = _new_external_paths(
        source_path,
        manifest_path,
        receipt_path,
        repo_root=repo_root,
    )
    prepared_at = clock()
    if prepared_at.tzinfo is None or prepared_at.utcoffset() is None:
        raise RuntimeError("credential preparation clock must be timezone-aware")
    execution_host_id = str(execution_host_id_provider()).lower()
    if len(execution_host_id) != 64 or any(
        character not in "0123456789abcdef" for character in execution_host_id
    ):
        raise RuntimeError("credential preparation host identity is invalid")
    execution_principal_id = str(execution_principal_id_provider()).lower()
    if len(execution_principal_id) != 64 or any(
        character not in "0123456789abcdef"
        for character in execution_principal_id
    ):
        raise RuntimeError("credential preparation principal identity is invalid")
    manifest_output = _CreateOnlyOutput(
        manifest_out,
        label="credential reference manifest",
    )
    try:
        receipt_output = _CreateOnlyOutput(
            receipt_out,
            label="credential import receipt",
        )
    except BaseException:
        manifest_output.remove_if_owned()
        raise
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "FAIL",
        "platform": "polymarket_global",
        "prepared_at_utc": prepared_at.astimezone(timezone.utc).isoformat(),
        "execution_host_id": execution_host_id,
        "execution_principal_id": execution_principal_id,
        "source_outside_repository_verified": True,
        "source_acl_private_confirmed": True,
        "credential_value_count_expected": len(WINCRED_TARGETS),
        "credential_value_count_written": 0,
        "credential_mode": (
            "verify_existing_exact" if verify_existing_exact else "create_new"
        ),
        "credential_value_count_existing_exact_verified": 0,
        "credential_store_mutation_attempted": False,
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
    manifest_written = False
    try:
        values = _parse_source(_read_source_snapshot(source))
        bundle, checks = _validated_bundle(
            values,
            account_deriver=account_deriver,
        )
        receipt["checks"] = checks
        receipt["ignored_source_key_count"] = 0
        existing = [
            bool(credential_exists(target)) for target in WINCRED_TARGETS.values()
        ]
        if verify_existing_exact:
            if not all(existing):
                receipt["missing"] = [
                    "fixed_credential_targets_all_exist_and_match_source"
                ]
                raise RuntimeError(
                    "fixed credential targets could not be verified exactly"
                )
            comparisons = []
            for field, target in WINCRED_TARGETS.items():
                try:
                    actual_value = credential_reader(target)
                    matches = _secret_values_match(
                        actual_value,
                        getattr(bundle, field),
                    )
                except Exception:
                    matches = False
                comparisons.append(matches)
            if not all(comparisons):
                receipt["missing"] = [
                    "fixed_credential_targets_all_exist_and_match_source"
                ]
                raise RuntimeError(
                    "fixed credential targets could not be verified exactly"
                )
            receipt["credential_value_count_existing_exact_verified"] = len(
                comparisons
            )
        else:
            if any(existing):
                receipt["missing"] = ["fixed_credential_targets_are_new"]
                raise RuntimeError("one or more fixed credential targets already exist")
            receipt["credential_store_mutation_attempted"] = True
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
        manifest_output.write_json(manifest)
        manifest_output.verify()
        manifest_written = True
        receipt["status"] = "PASS"
    except BaseException as exc:
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
        if manifest_written and not manifest_output.remove_if_owned():
            rollback_ok = False
            receipt["rollback_ok"] = False
    if operation_error is not None:
        manifest_output.remove_if_owned()
    if operation_error is not None:
        receipt["exception_type"] = type(operation_error).__name__
    try:
        receipt_output.write_json(receipt)
        receipt_output.verify()
    except BaseException:
        if created_targets and not receipt["rollback_attempted"]:
            for target in reversed(created_targets):
                try:
                    credential_deleter(target)
                except Exception:
                    pass
        manifest_output.remove_if_owned()
        receipt_output.remove_if_owned()
        raise
    finally:
        manifest_output.close()
        receipt_output.close()
    if operation_error is not None:
        raise operation_error
    return {"manifest": manifest, "receipt": receipt}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-env", required=True)
    parser.add_argument("--manifest-out", required=True)
    parser.add_argument("--receipt-out", required=True)
    parser.add_argument("--sdk-overlay-manifest", required=True)
    parser.add_argument("--sdk-overlay-manifest-sha256", required=True)
    parser.add_argument("--confirm-source-acl-private", action="store_true")
    parser.add_argument("--verify-existing-exact", action="store_true")
    parser.add_argument("--confirmation", required=True)
    return parser


def _activate_sdk_overlay(manifest_path, expected_manifest_sha256):
    from weather.market.live_sdk_overlay import activate_live_sdk_overlay

    return activate_live_sdk_overlay(manifest_path, expected_manifest_sha256)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        sdk_activation = _activate_sdk_overlay(
            args.sdk_overlay_manifest,
            args.sdk_overlay_manifest_sha256,
        )
        if (
            not isinstance(sdk_activation, dict)
            or sdk_activation.get("status") != "PASS"
            or sdk_activation.get("process_path_activated") is not True
            or sdk_activation.get("shared_environment_mutated") is not False
        ):
            raise RuntimeError("sealed SDK overlay activation did not pass")
        result = import_live_pilot_credentials(
            args.source_env,
            args.manifest_out,
            args.receipt_out,
            confirmation=args.confirmation,
            source_acl_private_confirmed=args.confirm_source_acl_private,
            verify_existing_exact=args.verify_existing_exact,
        )
    except Exception as exc:
        print(f"credential import failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    receipt = result["receipt"]
    prepared_count = (
        receipt["credential_value_count_written"]
        + receipt["credential_value_count_existing_exact_verified"]
    )
    print(f"credential preparation PASS: {prepared_count} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
