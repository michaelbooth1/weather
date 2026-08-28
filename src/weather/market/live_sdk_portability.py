"""Offline export and import of the sealed public International live SDK.

This module copies only the already hash-pinned SDK overlay and wheelhouse.  It
does not activate the SDK, read credentials, contact a network or exchange, or
interact with capture or the Windows Task Scheduler.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import struct
import sys
import sysconfig
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

sys.dont_write_bytecode = True

from weather.execution_host import current_execution_host_id
from weather.market import live_sdk_overlay
from weather.paths import REPO_ROOT


BUNDLE_SCHEMA_VERSION = "international_live_sdk_public_bundle_v0.1"
RECEIPT_SCHEMA_VERSION = "international_live_sdk_portability_receipt_v0.1"
BUNDLE_MANIFEST_NAME = "bundle-manifest.json"
SDK_MANIFEST_NAME = "sdk-overlay-manifest.json"
BUNDLE_PROFILE_NAME = "profile"
EXPECTED_SDK_MANIFEST_SHA256 = (
    "2044d0570d38c34057c520ab19bfcc114c751fe8c76f97091b605acc1deecd13"
)
EXPORT_CONFIRMATION = "AUTHORIZE_NON_SECRET_INTERNATIONAL_LIVE_SDK_EXPORT"
IMPORT_CONFIRMATION = "AUTHORIZE_NON_SECRET_INTERNATIONAL_LIVE_SDK_IMPORT"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
NEGATIVE_AUTHORITY = {
    "authority": "PUBLIC_SDK_SUBSTRATE_ONLY_NO_LIVE_AUTHORITY",
    "artifact_authentication_proved": False,
    "bundle_contains_secrets": False,
    "capture_access": False,
    "capture_mutation": False,
    "credential_access": False,
    "credential_mutation": False,
    "credential_value_access": False,
    "credential_value_read": False,
    "exchange_contact": False,
    "exchange_mutation": False,
    "geographic_eligibility_proved": False,
    "live_readiness_authorized": False,
    "live_trading_authority": False,
    "network_access": False,
    "network_contact": False,
    "production_repository_mutation": False,
    "private_acl_proved": False,
    "sdk_runtime_activation": False,
    "scheduler_access": False,
    "scheduler_mutation": False,
}
REPOSITORY_ROOT = REPO_ROOT


class LiveSdkPortabilityError(RuntimeError):
    """Raised when the public SDK portability contract is not satisfied."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")


def _finalize_hash(payload: Mapping[str, Any], field: str) -> dict[str, Any]:
    finalized = dict(payload)
    if field in finalized:
        raise LiveSdkPortabilityError(f"{field} was present before finalization")
    finalized[field] = _sha256_bytes(_canonical_json_bytes(finalized))
    return finalized


def _verify_self_hash(payload: Mapping[str, Any], field: str) -> None:
    observed = str(payload.get(field) or "").lower()
    if SHA256_RE.fullmatch(observed) is None:
        raise LiveSdkPortabilityError(f"{field} is not a SHA-256")
    unhashed = dict(payload)
    unhashed.pop(field, None)
    if observed != _sha256_bytes(_canonical_json_bytes(unhashed)):
        raise LiveSdkPortabilityError(f"{field} does not match canonical content")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LiveSdkPortabilityError("JSON contains a duplicate object key")
        result[key] = value
    return result


def _read_json_exact(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raise LiveSdkPortabilityError("JSON must be UTF-8 without a BOM")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs)
    except LiveSdkPortabilityError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveSdkPortabilityError(f"unreadable JSON file: {path.name}") from exc
    if not isinstance(value, dict):
        raise LiveSdkPortabilityError(f"JSON root must be an object: {path.name}")
    return value, raw


def _exact_keys(value: Any, expected: set[str], *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise LiveSdkPortabilityError(f"{label} does not have the exact keys")
    return value


def _strict_json_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(
            _strict_json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _strict_json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    return left == right


def _is_reparse(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _lstat_or_none(path: Path):
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _reject_nonlocal_path(path: Path, *, label: str) -> None:
    raw = str(path)
    normalized = raw.replace("/", "\\")
    if "\x00" in raw or normalized.startswith("\\\\"):
        raise LiveSdkPortabilityError(f"{label} must not use a network or device path")
    if os.name != "nt":
        return
    drive = path.drive
    if re.fullmatch(r"[A-Za-z]:", drive) is None:
        raise LiveSdkPortabilityError(f"{label} must be on a local Windows drive")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetDriveTypeW.restype = ctypes.c_uint
    drive_type = int(kernel32.GetDriveTypeW(drive + "\\"))
    # DRIVE_REMOVABLE=2 and DRIVE_FIXED=3 are the only public-bundle media
    # accepted by this offline lane. In particular, DRIVE_REMOTE=4 is refused.
    if drive_type not in {2, 3}:
        raise LiveSdkPortabilityError(f"{label} must be on fixed or removable local media")


def _absolute_existing_directory(path: str | Path, *, label: str) -> Path:
    raw = Path(path)
    if not raw.is_absolute():
        raise LiveSdkPortabilityError(f"{label} must be absolute")
    _reject_nonlocal_path(raw, label=label)
    cursor = Path(raw.anchor)
    for part in raw.parts[1:]:
        cursor /= part
        if _lstat_or_none(cursor) is not None and _is_reparse(cursor):
            raise LiveSdkPortabilityError(f"{label} contains a redirected entry")
    resolved = raw.resolve()
    if not resolved.is_dir() or _is_reparse(resolved):
        raise LiveSdkPortabilityError(f"{label} is absent or redirected")
    return resolved


def _absolute_existing_file(path: str | Path, *, label: str) -> Path:
    raw = Path(path)
    if not raw.is_absolute():
        raise LiveSdkPortabilityError(f"{label} must be absolute")
    _reject_nonlocal_path(raw, label=label)
    _absolute_existing_directory(raw.parent, label=f"{label} parent")
    if _lstat_or_none(raw) is None or _is_reparse(raw) or not raw.is_file():
        raise LiveSdkPortabilityError(f"{label} is absent or redirected")
    return raw.resolve()


def _absolute_new_path(path: str | Path, *, label: str) -> Path:
    raw = Path(path)
    if not raw.is_absolute():
        raise LiveSdkPortabilityError(f"{label} must be absolute")
    _reject_nonlocal_path(raw, label=label)
    parent = _absolute_existing_directory(raw.parent, label=f"{label} parent")
    target = parent / raw.name
    if _lstat_or_none(target) is not None:
        raise LiveSdkPortabilityError(f"{label} already exists")
    return target


def _windows_component(component: str, *, label: str) -> None:
    if (
        not component
        or unicodedata.normalize("NFC", component) != component
        or component in {".", ".."}
        or ":" in component
        or component.endswith((" ", "."))
        or component.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES
        or any(ord(character) < 32 for character in component)
    ):
        raise LiveSdkPortabilityError(f"{label} is not a safe Windows path")


def _safe_relative_path(value: Any, *, label: str) -> PurePosixPath:
    if not isinstance(value, str) or "\\" in value:
        raise LiveSdkPortabilityError(f"{label} must be a canonical POSIX path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or not relative.parts:
        raise LiveSdkPortabilityError(f"{label} must be relative")
    for component in relative.parts:
        _windows_component(component, label=label)
    return relative


def _assert_no_windows_collisions(paths: Sequence[PurePosixPath]) -> None:
    normalized: set[str] = set()
    for path in paths:
        key = unicodedata.normalize("NFC", str(path)).casefold()
        if key in normalized:
            raise LiveSdkPortabilityError("bundle paths collide under Windows case folding")
        normalized.add(key)


def _windows_identity() -> dict[str, str]:
    if os.name != "nt":
        return {"computer_name": platform.node(), "user_name": "", "user_sid": ""}
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    advapi32.OpenProcessToken.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.OpenProcessToken.restype = ctypes.c_int
    advapi32.GetTokenInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    advapi32.GetTokenInformation.restype = ctypes.c_int
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.ConvertSidToStringSidW.restype = ctypes.c_int
    computer_size = ctypes.c_ulong(32768)
    computer_buffer = ctypes.create_unicode_buffer(computer_size.value)
    if not kernel32.GetComputerNameW(computer_buffer, ctypes.byref(computer_size)):
        raise LiveSdkPortabilityError("Windows computer identity is unavailable")
    user_size = ctypes.c_ulong(32768)
    user_buffer = ctypes.create_unicode_buffer(user_size.value)
    if not advapi32.GetUserNameW(user_buffer, ctypes.byref(user_size)):
        raise LiveSdkPortabilityError("Windows account identity is unavailable")

    token = ctypes.c_void_p()
    TOKEN_QUERY = 0x0008
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)
    ):
        raise LiveSdkPortabilityError("Windows process identity token is unavailable")
    try:
        required = ctypes.c_ulong(0)
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        token_info = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token, 1, token_info, required, ctypes.byref(required)
        ):
            raise LiveSdkPortabilityError("Windows token user identity is unavailable")
        sid_pointer = ctypes.cast(token_info, ctypes.POINTER(ctypes.c_void_p))[0]
        sid_string = ctypes.c_void_p()
        if not advapi32.ConvertSidToStringSidW(sid_pointer, ctypes.byref(sid_string)):
            raise LiveSdkPortabilityError("Windows account SID is unavailable")
        try:
            sid = ctypes.wstring_at(sid_string)
        finally:
            kernel32.LocalFree(sid_string)
    finally:
        kernel32.CloseHandle(token)
    return {
        "computer_name": computer_buffer.value,
        "user_name": user_buffer.value,
        "user_sid": sid,
    }


def _host_evidence() -> dict[str, Any]:
    implementation = platform.python_implementation()
    machine = platform.machine()
    pointer_bits = struct.calcsize("P") * 8
    executable = Path(sys.executable)
    windows_identity = _windows_identity()
    ambient_computer = str(os.environ.get("COMPUTERNAME") or "").strip()
    ambient_user = str(os.environ.get("USERNAME") or "").strip()
    try:
        resolved_executable = _absolute_existing_file(
            executable, label="Python executable"
        )
        executable_regular = True
    except LiveSdkPortabilityError:
        resolved_executable = executable.absolute()
        executable_regular = False
    checks = {
        "windows": os.name == "nt" and platform.system() == "Windows",
        "machine_amd64": machine.lower() in {"amd64", "x86_64"},
        "pointer_width_64": pointer_bits == 64,
        "cpython": implementation == "CPython" and sys.implementation.name == "cpython",
        "python_3_11": sys.version_info[:2] == (3, 11),
        "python_executable_regular": executable_regular,
        "sysconfig_win_amd64": sysconfig.get_platform().lower() == "win-amd64",
        "ambient_computer_matches_os": (
            bool(ambient_computer)
            and ambient_computer.casefold()
            == windows_identity["computer_name"].casefold()
        ),
        "ambient_user_matches_os": (
            bool(ambient_user)
            and ambient_user.casefold() == windows_identity["user_name"].casefold()
        ),
    }
    try:
        execution_host_id = current_execution_host_id()
    except RuntimeError as exc:
        raise LiveSdkPortabilityError(
            "Windows installation identity is unavailable"
        ) from exc
    evidence = {
        "checks": checks,
        "compatible": all(checks.values()),
        "implementation": implementation,
        "machine": machine,
        "pointer_bits": pointer_bits,
        "python_version": platform.python_version(),
        "python_executable": str(resolved_executable),
        "python_executable_sha256": (
            _sha256_file(resolved_executable) if executable_regular else None
        ),
        "system": platform.system(),
        "windows_identity": windows_identity,
        "execution_host_id": execution_host_id,
        "execution_host_id_contract": (
            "international_live_execution_host_v2:windows_machine_guid"
        ),
    }
    if not evidence["compatible"]:
        failed = ", ".join(name for name, passed in checks.items() if not passed)
        raise LiveSdkPortabilityError(
            "public SDK portability requires Windows x64 CPython 3.11; failed: "
            + failed
        )
    return evidence


def _current_profile_root() -> Path:
    return _absolute_existing_directory(
        live_sdk_overlay.current_live_sdk_profile_root(),
        label="current user profile",
    )


def _sdk_manifest_payload(path: Path, expected_sha256: str) -> tuple[dict[str, Any], bytes]:
    path = _absolute_existing_file(path, label="SDK overlay manifest")
    payload, raw = _read_json_exact(path)
    expected = str(expected_sha256).lower()
    if SHA256_RE.fullmatch(expected) is None or _sha256_bytes(raw) != expected:
        raise LiveSdkPortabilityError("SDK overlay manifest hash changed")
    # The canonical validator owns the exact SDK schema and content contract.
    return payload, raw


def _contract_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    overlay = payload["overlay"]
    wheelhouse = payload["wheelhouse"]
    return {
        "distribution": payload["distribution"],
        "import_package": payload["import_package"],
        "version": payload["version"],
        "overlay": {
            key: overlay[key]
            for key in (
                "relative_path",
                "file_count",
                "bytes",
                "tree_manifest_sha256",
                "metadata_relative_path",
                "metadata_sha256",
                "package_init_relative_path",
                "package_init_sha256",
            )
        },
        "wheelhouse": {
            key: wheelhouse[key]
            for key in (
                "relative_path",
                "file_count",
                "bytes",
                "name_hash_manifest_sha256",
                "ordered_file_names",
                "core_wheel_name",
                "core_wheel_sha256",
            )
        },
    }


def _bundle_manifest(payload: Mapping[str, Any], sdk_manifest_sha256: str) -> dict[str, Any]:
    return _finalize_hash(
        {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "bundle_kind": "public_non_secret_international_live_sdk",
            "sdk_overlay_manifest": {
                "relative_path": SDK_MANIFEST_NAME,
                "sha256": sdk_manifest_sha256,
            },
            "profile_root_relative_path": BUNDLE_PROFILE_NAME,
            "target_runtime": {
                "implementation": "CPython",
                "machine": "AMD64",
                "operating_system": "Windows",
                "pointer_bits": 64,
                "python_major": 3,
                "python_minor": 11,
            },
            "sdk_contract": _contract_summary(payload),
            "authority": dict(NEGATIVE_AUTHORITY),
        },
        "bundle_sha256",
    )


def _manifest_relative_roots(payload: Mapping[str, Any]) -> tuple[PurePosixPath, PurePosixPath]:
    overlay = _safe_relative_path(payload["overlay"]["relative_path"], label="overlay path")
    wheelhouse = _safe_relative_path(
        payload["wheelhouse"]["relative_path"], label="wheelhouse path"
    )
    if overlay == wheelhouse or overlay in wheelhouse.parents or wheelhouse in overlay.parents:
        raise LiveSdkPortabilityError("SDK profile roots overlap")
    _assert_no_windows_collisions([overlay, wheelhouse])
    return overlay, wheelhouse


def _validate_wheel_target_contract(payload: Mapping[str, Any]) -> None:
    names = payload["wheelhouse"]["ordered_file_names"]
    if not isinstance(names, list) or not names:
        raise LiveSdkPortabilityError("wheelhouse filename contract is empty")
    native_cp311 = False
    for name in names:
        relative = _safe_relative_path(name, label="wheel filename")
        if len(relative.parts) != 1 or not name.lower().endswith(".whl"):
            raise LiveSdkPortabilityError("wheelhouse filename is not canonical")
        try:
            _build, python_tag, abi_tag, platform_tag = name[:-4].rsplit("-", 3)
        except ValueError as exc:
            raise LiveSdkPortabilityError("wheelhouse filename has invalid tags") from exc
        platforms = platform_tag.lower().split(".")
        if any(tag not in {"any", "win_amd64"} for tag in platforms):
            raise LiveSdkPortabilityError("wheelhouse contains a non-Windows-x64 wheel")
        python_tags = python_tag.lower().split(".")
        abi_tags = abi_tag.lower().split(".")
        compatible = False
        for candidate_python in python_tags:
            for candidate_abi in abi_tags:
                for candidate_platform in platforms:
                    pure_compatible = (
                        candidate_platform == "any"
                        and candidate_abi == "none"
                        and candidate_python in {"py3", "py311", "cp311"}
                    )
                    exact_native = (
                        candidate_platform == "win_amd64"
                        and candidate_python == "cp311"
                        and candidate_abi in {"cp311", "abi3"}
                    )
                    abi3_compatible = False
                    match = re.fullmatch(r"cp3(\d{1,2})", candidate_python)
                    if (
                        candidate_platform == "win_amd64"
                        and candidate_abi == "abi3"
                        and match is not None
                    ):
                        abi3_compatible = int(match.group(1)) <= 11
                    compatible = compatible or pure_compatible or exact_native or abi3_compatible
                    native_cp311 = native_cp311 or exact_native
        if not compatible:
            raise LiveSdkPortabilityError(
                "wheelhouse contains a wheel incompatible with CPython 3.11 x64"
            )
    if not native_cp311:
        raise LiveSdkPortabilityError("wheelhouse does not prove a CPython 3.11 x64 target")


def _inventory(root: Path) -> tuple[set[PurePosixPath], set[PurePosixPath]]:
    files: set[PurePosixPath] = set()
    directories: set[PurePosixPath] = set()
    for entry in root.rglob("*"):
        if _is_reparse(entry):
            raise LiveSdkPortabilityError("public SDK tree contains a redirected entry")
        relative = PurePosixPath(entry.relative_to(root).as_posix())
        _safe_relative_path(relative.as_posix(), label="public SDK tree entry")
        if entry.is_file():
            files.add(relative)
        elif entry.is_dir():
            directories.add(relative)
        else:
            raise LiveSdkPortabilityError("public SDK tree contains a special entry")
    _assert_no_windows_collisions(sorted(files | directories, key=str))
    return files, directories


def _expected_profile_inventory(
    profile_root: Path,
    payload: Mapping[str, Any],
    manifest_path: Path,
    manifest_sha256: str,
) -> tuple[set[PurePosixPath], set[PurePosixPath]]:
    file_hashes = live_sdk_overlay.validated_live_sdk_overlay_file_hashes(
        manifest_path,
        manifest_sha256,
        profile_root=profile_root,
    )
    overlay_relative, wheelhouse_relative = _manifest_relative_roots(payload)
    overlay_root = profile_root.joinpath(*overlay_relative.parts).resolve()
    expected_files = {
        overlay_relative / PurePosixPath(Path(path).resolve().relative_to(overlay_root).as_posix())
        for path in file_hashes
    }
    expected_files.update(
        wheelhouse_relative / _safe_relative_path(name, label="wheel filename")
        for name in payload["wheelhouse"]["ordered_file_names"]
    )
    expected_directories: set[PurePosixPath] = set()
    for path in expected_files:
        expected_directories.update(parent for parent in path.parents if parent.parts)
    return expected_files, expected_directories


def _validate_profile_exact(
    profile_root: Path,
    payload: Mapping[str, Any],
    manifest_path: Path,
    manifest_sha256: str,
) -> dict[str, Any]:
    validation = _validate_sdk_roots_exact(
        manifest_path,
        manifest_sha256,
        profile_root=profile_root,
    )
    _validate_wheel_target_contract(payload)
    actual_files, actual_directories = _inventory(profile_root)
    expected_files, expected_directories = _expected_profile_inventory(
        profile_root, payload, manifest_path, manifest_sha256
    )
    if actual_files != expected_files or actual_directories != expected_directories:
        raise LiveSdkPortabilityError("public SDK bundle profile has unexpected entries")
    return validation


def _validate_sdk_roots_exact(
    manifest_path: Path,
    manifest_sha256: str,
    *,
    profile_root: Path,
) -> dict[str, Any]:
    validation = live_sdk_overlay.validate_live_sdk_overlay(
        manifest_path,
        manifest_sha256,
        profile_root=profile_root,
    )
    _validate_overlay_directories_exact(Path(validation["overlay"]["root"]))
    return validation


def _validate_overlay_directories_exact(overlay_root: Path) -> None:
    actual_directories = {
        PurePosixPath(path.relative_to(overlay_root).as_posix())
        for path in overlay_root.rglob("*")
        if path.is_dir()
    }
    files = {
        PurePosixPath(path.relative_to(overlay_root).as_posix())
        for path in overlay_root.rglob("*")
        if path.is_file()
    }
    expected_directories: set[PurePosixPath] = set()
    for path in files:
        expected_directories.update(parent for parent in path.parents if parent.parts)
    if actual_directories != expected_directories:
        raise LiveSdkPortabilityError(
            "SDK overlay contains an unbound empty directory"
        )


def _validate_sdk_component_exact(
    profile: Path,
    payload: Mapping[str, Any],
    component: str,
) -> dict[str, Any]:
    try:
        if component == "overlay":
            summary = live_sdk_overlay._validate_overlay(
                payload["overlay"],
                profile_root=profile,
            )
            _validate_overlay_directories_exact(Path(summary["root"]))
            return summary
        if component == "wheelhouse":
            return live_sdk_overlay._validate_wheelhouse(
                payload["wheelhouse"],
                profile_root=profile,
            )
    except (live_sdk_overlay.LiveSdkOverlayError, OSError) as exc:
        raise LiveSdkPortabilityError(
            f"destination partial {component} conflicts with the trusted bundle"
        ) from exc
    raise LiveSdkPortabilityError("SDK component name is unsupported")


def validate_public_sdk_bundle(
    bundle_root: str | Path,
    *,
    expected_sdk_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    root = _absolute_existing_directory(bundle_root, label="public SDK bundle")
    top_names = {entry.name for entry in root.iterdir()}
    if top_names != {BUNDLE_MANIFEST_NAME, SDK_MANIFEST_NAME, BUNDLE_PROFILE_NAME}:
        raise LiveSdkPortabilityError("public SDK bundle has unexpected top-level entries")
    for entry in root.iterdir():
        if _is_reparse(entry):
            raise LiveSdkPortabilityError("public SDK bundle contains a redirected entry")
    bundle_payload, bundle_raw = _read_json_exact(root / BUNDLE_MANIFEST_NAME)
    _exact_keys(
        bundle_payload,
        {
            "schema_version",
            "bundle_kind",
            "sdk_overlay_manifest",
            "profile_root_relative_path",
            "target_runtime",
            "sdk_contract",
            "authority",
            "bundle_sha256",
        },
        label="public SDK bundle manifest",
    )
    _verify_self_hash(bundle_payload, "bundle_sha256")
    if bundle_raw != _canonical_json_bytes(bundle_payload):
        raise LiveSdkPortabilityError("public SDK bundle manifest is not canonical JSON")
    if (
        bundle_payload["schema_version"] != BUNDLE_SCHEMA_VERSION
        or bundle_payload["bundle_kind"] != "public_non_secret_international_live_sdk"
        or bundle_payload["profile_root_relative_path"] != BUNDLE_PROFILE_NAME
        or not _strict_json_equal(bundle_payload["authority"], NEGATIVE_AUTHORITY)
    ):
        raise LiveSdkPortabilityError("public SDK bundle identity or authority changed")
    target_runtime = _exact_keys(
        bundle_payload["target_runtime"],
        {
            "implementation",
            "machine",
            "operating_system",
            "pointer_bits",
            "python_major",
            "python_minor",
        },
        label="target runtime",
    )
    if not _strict_json_equal(
        target_runtime,
        {
            "implementation": "CPython",
            "machine": "AMD64",
            "operating_system": "Windows",
            "pointer_bits": 64,
            "python_major": 3,
            "python_minor": 11,
        },
    ):
        raise LiveSdkPortabilityError("public SDK bundle target runtime changed")
    sdk_record = _exact_keys(
        bundle_payload["sdk_overlay_manifest"],
        {"relative_path", "sha256"},
        label="SDK manifest binding",
    )
    if sdk_record["relative_path"] != SDK_MANIFEST_NAME:
        raise LiveSdkPortabilityError("public SDK bundle manifest path changed")
    manifest_sha256 = str(sdk_record["sha256"]).lower()
    trusted_manifest_sha256 = (
        EXPECTED_SDK_MANIFEST_SHA256
        if expected_sdk_manifest_sha256 is None
        else str(expected_sdk_manifest_sha256).lower()
    )
    if manifest_sha256 != trusted_manifest_sha256:
        raise LiveSdkPortabilityError("public SDK bundle is not the expected exact SDK")
    manifest_path = root / SDK_MANIFEST_NAME
    sdk_payload, sdk_raw = _sdk_manifest_payload(manifest_path, manifest_sha256)
    profile_root = _absolute_existing_directory(
        root / BUNDLE_PROFILE_NAME, label="bundle profile"
    )
    validation = _validate_profile_exact(
        profile_root, sdk_payload, manifest_path, manifest_sha256
    )
    if not _strict_json_equal(
        bundle_payload["sdk_contract"], _contract_summary(sdk_payload)
    ):
        raise LiveSdkPortabilityError("public SDK bundle contract summary changed")
    return {
        "bundle_root": str(root),
        "bundle_manifest_path": str(root / BUNDLE_MANIFEST_NAME),
        "bundle_manifest_file_sha256": _sha256_bytes(bundle_raw),
        "bundle_sha256": bundle_payload["bundle_sha256"],
        "sdk_manifest_path": str(manifest_path),
        "sdk_manifest_sha256": _sha256_bytes(sdk_raw),
        "sdk_payload": sdk_payload,
        "sdk_validation": validation,
        "profile_root": str(profile_root),
    }


def _copy_file_new(source: Path, destination: Path) -> None:
    if not source.is_file() or _is_reparse(source):
        raise LiveSdkPortabilityError("SDK copy source is absent or redirected")
    before = (source.stat().st_size, _sha256_file(source))
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
        0o600,
    )
    try:
        with source.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
            descriptor = -1
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    after = (source.stat().st_size, _sha256_file(source))
    if before != after or _sha256_file(destination) != before[1]:
        raise LiveSdkPortabilityError("SDK source changed while it was copied")


def _copy_tree_new(source: Path, destination: Path) -> None:
    if _lstat_or_none(destination) is not None:
        raise LiveSdkPortabilityError("SDK copy destination already exists")
    destination.mkdir()
    entries = sorted(source.rglob("*"), key=lambda path: path.relative_to(source).as_posix())
    for entry in entries:
        if _is_reparse(entry):
            raise LiveSdkPortabilityError("SDK copy source contains a redirected entry")
        if not entry.is_dir() and not entry.is_file():
            raise LiveSdkPortabilityError("SDK copy source contains a special entry")
    for entry in (path for path in entries if path.is_file()):
        relative = entry.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _copy_file_new(entry, target)


def _remove_owned_staging_tree(staging: Path) -> None:
    """Remove only one invocation-owned, non-redirected staging tree."""

    if _lstat_or_none(staging) is None:
        return
    if _is_reparse(staging) or not staging.is_dir():
        raise LiveSdkPortabilityError(
            "SDK staging cleanup refused a redirected or special root"
        )
    files: list[Path] = []
    directories: list[Path] = []

    def inventory(directory: Path) -> None:
        try:
            with os.scandir(directory) as scanner:
                children = list(scanner)
        except OSError as exc:
            raise LiveSdkPortabilityError(
                "SDK staging cleanup could not inventory its private tree"
            ) from exc
        for child in children:
            child_path = Path(child.path)
            try:
                child_stat = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise LiveSdkPortabilityError(
                    "SDK staging cleanup entry changed during inventory"
                ) from exc
            child_reparse = child.is_symlink() or bool(
                getattr(child_stat, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            )
            if child_reparse:
                raise LiveSdkPortabilityError(
                    "SDK staging cleanup refused a redirected entry"
                )
            if stat.S_ISREG(child_stat.st_mode):
                files.append(child_path)
            elif stat.S_ISDIR(child_stat.st_mode):
                inventory(child_path)
                directories.append(child_path)
            else:
                raise LiveSdkPortabilityError(
                    "SDK staging cleanup refused a special entry"
                )

    inventory(staging)
    for entry in files:
        observed = entry.lstat()
        if _is_reparse(entry) or not stat.S_ISREG(observed.st_mode):
            raise LiveSdkPortabilityError(
                "SDK staging cleanup entry changed before deletion"
            )
        entry.unlink()
    for entry in directories:
        observed = entry.lstat()
        if _is_reparse(entry) or not stat.S_ISDIR(observed.st_mode):
            raise LiveSdkPortabilityError(
                "SDK staging cleanup directory changed before deletion"
            )
        entry.rmdir()
    if _is_reparse(staging) or not staging.is_dir():
        raise LiveSdkPortabilityError(
            "SDK staging cleanup root changed before deletion"
        )
    staging.rmdir()


def _write_new_or_exact(path: Path, payload: Mapping[str, Any]) -> str:
    raw = _canonical_json_bytes(payload)
    if _lstat_or_none(path) is not None:
        if path.is_file() and not _is_reparse(path) and path.read_bytes() == raw:
            return "ALREADY_PRESENT_EXACT"
        raise LiveSdkPortabilityError(f"refusing to overwrite changed output: {path.name}")
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
    except FileExistsError:
        if path.is_file() and not _is_reparse(path) and path.read_bytes() == raw:
            return "ALREADY_PRESENT_EXACT"
        raise LiveSdkPortabilityError(
            f"refusing to overwrite changed output: {path.name}"
        ) from None
    except OSError as exc:
        raise LiveSdkPortabilityError(
            f"unable to create public SDK output: {path.name}"
        ) from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return "CREATED"


def _move_no_replace(source: Path, destination: Path) -> None:
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.MoveFileExW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
        kernel32.MoveFileExW.restype = ctypes.c_int
        # MOVEFILE_WRITE_THROUGH requests durable completion while the absence
        # of MOVEFILE_REPLACE_EXISTING preserves the no-overwrite contract.
        if not kernel32.MoveFileExW(str(source), str(destination), 0x00000008):
            error = ctypes.get_last_error()
            raise LiveSdkPortabilityError(
                f"no-replace SDK publication failed with Windows error {error}"
            )
    else:  # pragma: no cover - the host gate prevents production use here.
        if _lstat_or_none(destination) is not None:
            raise LiveSdkPortabilityError("SDK publication destination appeared")
        os.rename(source, destination)


def _rollback_published_roots(
    published: Sequence[tuple[Path, Path]],
) -> list[str]:
    """Move every published directory back or report an exact rollback failure."""

    failures: list[str] = []
    for destination, source in reversed(published):
        try:
            if _lstat_or_none(source) is not None:
                raise LiveSdkPortabilityError(
                    "SDK rollback source unexpectedly exists"
                )
            destination_stat = _lstat_or_none(destination)
            if (
                destination_stat is None
                or _is_reparse(destination)
                or not stat.S_ISDIR(destination_stat.st_mode)
            ):
                raise LiveSdkPortabilityError(
                    "SDK rollback destination is absent, redirected, or special"
                )
            _move_no_replace(destination, source)
            source_stat = _lstat_or_none(source)
            if (
                _lstat_or_none(destination) is not None
                or source_stat is None
                or _is_reparse(source)
                or not stat.S_ISDIR(source_stat.st_mode)
            ):
                raise LiveSdkPortabilityError(
                    "SDK rollback move-back did not produce the exact state"
                )
        except (LiveSdkPortabilityError, OSError) as exc:
            failures.append(str(exc))
    return failures


def _new_staging(parent: Path, stem: str) -> Path:
    prefix = f".{stem}.staging-"
    try:
        with os.scandir(parent) as scanner:
            stale = sorted(
                entry.name
                for entry in scanner
                if entry.name.startswith(prefix)
            )
    except OSError as exc:
        raise LiveSdkPortabilityError(
            "SDK staging parent could not be inventoried"
        ) from exc
    if stale:
        raise LiveSdkPortabilityError(
            "stale private SDK staging requires reviewed cleanup before retry"
        )
    staging = parent / f".{stem}.staging-{uuid.uuid4().hex}"
    staging.mkdir()
    return staging


def _receipt(
    *,
    operation: str,
    result: str,
    host: Mapping[str, Any],
    evidence: Mapping[str, Any],
    mutations: Mapping[str, bool],
    substrate_status: str,
) -> dict[str, Any]:
    mutation_claims = dict(mutations)
    mutation_claims["receipt_created"] = True
    return _finalize_hash(
        {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "status": "PASS",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "result": result,
            "substrate_status": substrate_status,
            "host": dict(host),
            "evidence": dict(evidence),
            "public_filesystem_mutations": mutation_claims,
            "authority": dict(NEGATIVE_AUTHORITY),
            "tool_identity": _tool_identity(),
        },
        "receipt_sha256",
    )


def _tool_identity() -> dict[str, Any]:
    paths = {
        "live_sdk_portability.py": Path(__file__),
        "live_sdk_overlay.py": Path(live_sdk_overlay.__file__),
        "portable_live_sdk.ps1": REPOSITORY_ROOT / "scripts/ops/portable_live_sdk.ps1",
    }
    files: dict[str, Any] = {}
    for label, path in paths.items():
        exact = _absolute_existing_file(path, label=f"tool source {label}")
        files[label] = {
            "path": str(exact),
            "sha256": _sha256_file(exact),
        }
    return {
        "repository_root": str(REPOSITORY_ROOT),
        "files": files,
        "repository_commit_bound": False,
        "repository_cleanliness_bound": False,
        "loaded_source_generation_bound": False,
    }


def _write_receipt(path: str | Path, receipt: Mapping[str, Any]) -> str:
    raw = Path(path)
    if not raw.is_absolute():
        raise LiveSdkPortabilityError("receipt path must be absolute")
    parent = _absolute_existing_directory(raw.parent, label="receipt parent")
    _windows_component(raw.name, label="receipt filename")
    target = parent / raw.name
    _reject_repository_output(target, label="receipt output")
    if _lstat_or_none(target) is not None:
        raise LiveSdkPortabilityError(
            "refusing to overwrite; receipt output must be new"
        )
    raw_receipt = _canonical_json_bytes(receipt)
    try:
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
    except FileExistsError as exc:
        raise LiveSdkPortabilityError(
            "refusing to overwrite; receipt output must be new"
        ) from exc
    except OSError as exc:
        raise LiveSdkPortabilityError("unable to create portability receipt") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(raw_receipt)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return "CREATED"


def _preflight_receipt_path(path: str | Path, *, target_will_mutate: bool) -> None:
    raw = Path(path)
    if not raw.is_absolute():
        raise LiveSdkPortabilityError("receipt path must be absolute")
    parent = _absolute_existing_directory(raw.parent, label="receipt parent")
    _windows_component(raw.name, label="receipt filename")
    target = parent / raw.name
    _reject_repository_output(target, label="receipt output")
    if target_will_mutate and _lstat_or_none(target) is not None:
        raise LiveSdkPortabilityError(
            "receipt output must be new before a public SDK mutation"
        )


def _refuse_receipt_overlap(path: str | Path, roots: Sequence[Path]) -> None:
    raw = Path(path)
    _reject_nonlocal_path(raw, label="receipt output")
    if not raw.is_absolute():
        raise LiveSdkPortabilityError("receipt path must be absolute")
    parent = _absolute_existing_directory(raw.parent, label="receipt parent")
    receipt = parent / raw.name
    for root in roots:
        resolved_root = root.resolve()
        if receipt == resolved_root or resolved_root in receipt.parents:
            raise LiveSdkPortabilityError(
                "receipt output must remain outside sealed SDK content"
            )


def _reject_repository_output(path: Path, *, label: str) -> None:
    _reject_nonlocal_path(path, label=label)
    repository = _absolute_existing_directory(
        REPOSITORY_ROOT, label="repository root"
    )
    resolved = path.resolve()
    if resolved == repository or repository in resolved.parents:
        raise LiveSdkPortabilityError(f"{label} must remain outside the repository")


def audit_installed_sdk(
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    *,
    profile_root: str | Path | None = None,
    receipt_out: str | Path,
) -> dict[str, Any]:
    host = _host_evidence()
    profile = (
        _current_profile_root()
        if profile_root is None
        else _absolute_existing_directory(profile_root, label="validation profile")
    )
    manifest = _absolute_existing_file(
        manifest_path, label="SDK overlay manifest"
    )
    payload, raw = _sdk_manifest_payload(manifest, expected_manifest_sha256)
    overlay_relative, wheelhouse_relative = _manifest_relative_roots(payload)
    _refuse_receipt_overlap(
        receipt_out,
        [
            profile.joinpath(*overlay_relative.parts),
            profile.joinpath(*wheelhouse_relative.parts),
            manifest,
        ],
    )
    _preflight_receipt_path(receipt_out, target_will_mutate=False)
    validation = _validate_sdk_roots_exact(
        manifest,
        expected_manifest_sha256,
        profile_root=profile,
    )
    receipt = _receipt(
        operation="audit-installed",
        result="VALIDATED_EXACT",
        host=host,
        evidence={
            "profile_root": str(profile),
            "sdk_manifest_path": str(manifest),
            "sdk_manifest_sha256": _sha256_bytes(raw),
            "sdk_contract": _contract_summary(payload),
            "sdk_validation": validation,
        },
        mutations={"bundle_created": False, "profile_created": False},
        substrate_status="PUBLIC_SDK_SUBSTRATE_VALIDATED",
    )
    _write_receipt(receipt_out, receipt)
    return receipt


def audit_sdk_bundle(
    bundle_root: str | Path,
    *,
    receipt_out: str | Path,
) -> dict[str, Any]:
    host = _host_evidence()
    _preflight_receipt_path(receipt_out, target_will_mutate=False)
    evidence = validate_public_sdk_bundle(bundle_root)
    _refuse_receipt_overlap(receipt_out, [Path(evidence["bundle_root"])])
    public_evidence = {key: value for key, value in evidence.items() if key != "sdk_payload"}
    receipt = _receipt(
        operation="audit-bundle",
        result="VALIDATED_EXACT",
        host=host,
        evidence=public_evidence,
        mutations={"bundle_created": False, "profile_created": False},
        substrate_status="PUBLIC_SDK_BUNDLE_VALIDATED_ONLY",
    )
    _write_receipt(receipt_out, receipt)
    return receipt


def export_public_sdk_bundle(
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    bundle_root: str | Path,
    *,
    confirmation: str,
    receipt_out: str | Path,
) -> dict[str, Any]:
    if confirmation != EXPORT_CONFIRMATION:
        raise LiveSdkPortabilityError("exact public SDK export confirmation is required")
    host = _host_evidence()
    source_profile = _current_profile_root()
    manifest = _absolute_existing_file(
        manifest_path, label="SDK overlay manifest"
    )
    payload, manifest_raw = _sdk_manifest_payload(manifest, expected_manifest_sha256)
    source_validation = _validate_sdk_roots_exact(
        manifest,
        expected_manifest_sha256,
        profile_root=source_profile,
    )
    target_input = Path(bundle_root)
    if not target_input.is_absolute():
        raise LiveSdkPortabilityError("bundle root must be absolute")
    target_parent = _absolute_existing_directory(
        target_input.parent, label="bundle parent"
    )
    target = target_parent / target_input.name
    _windows_component(target.name, label="bundle directory name")
    _reject_repository_output(target, label="bundle root")
    overlay_relative, wheelhouse_relative = _manifest_relative_roots(payload)
    _refuse_receipt_overlap(
        receipt_out,
        [
            target,
            source_profile.joinpath(*overlay_relative.parts),
            source_profile.joinpath(*wheelhouse_relative.parts),
            manifest,
        ],
    )
    result = "CREATED"
    bundle_created = False
    if _lstat_or_none(target) is not None:
        existing = validate_public_sdk_bundle(
            target,
            expected_sdk_manifest_sha256=expected_manifest_sha256,
        )
        if existing["sdk_manifest_sha256"] != str(expected_manifest_sha256).lower():
            raise LiveSdkPortabilityError("existing bundle has a different SDK contract")
        result = "ALREADY_PRESENT_EXACT"
        bundle_evidence = existing
    else:
        _preflight_receipt_path(receipt_out, target_will_mutate=True)
        source_overlay = source_profile.joinpath(*overlay_relative.parts)
        source_wheelhouse = source_profile.joinpath(*wheelhouse_relative.parts)
        if target == source_profile or source_profile in target.parents:
            raise LiveSdkPortabilityError("bundle destination overlaps the source profile")
        staging = _new_staging(target_parent, target.name)
        try:
            profile_staging = staging / BUNDLE_PROFILE_NAME
            profile_staging.mkdir()
            for relative, source in (
                (overlay_relative, source_overlay),
                (wheelhouse_relative, source_wheelhouse),
            ):
                parent = profile_staging
                for component in relative.parts[:-1]:
                    parent /= component
                    parent.mkdir(exist_ok=True)
                _copy_tree_new(source, parent / relative.name)
            _copy_file_new(manifest, staging / SDK_MANIFEST_NAME)
            bundle_payload = _bundle_manifest(payload, _sha256_bytes(manifest_raw))
            _write_new_or_exact(staging / BUNDLE_MANIFEST_NAME, bundle_payload)
            staged_evidence = validate_public_sdk_bundle(
                staging,
                expected_sdk_manifest_sha256=expected_manifest_sha256,
            )
            for key in ("overlay", "wheelhouse"):
                staged_summary = dict(staged_evidence["sdk_validation"][key])
                source_summary = dict(source_validation[key])
                staged_summary.pop("root", None)
                source_summary.pop("root", None)
                if staged_summary != source_summary:
                    raise LiveSdkPortabilityError(
                        f"exported {key} differs from its source"
                    )
            _move_no_replace(staging, target)
        finally:
            _remove_owned_staging_tree(staging)
        bundle_created = True
        bundle_evidence = validate_public_sdk_bundle(
            target,
            expected_sdk_manifest_sha256=expected_manifest_sha256,
        )
    public_evidence = {
        key: value for key, value in bundle_evidence.items() if key != "sdk_payload"
    }
    receipt = _receipt(
        operation="export",
        result=result,
        host=host,
        evidence=public_evidence,
        mutations={
            "bundle_created": bundle_created,
            "bundle_staging_created_and_published": bundle_created,
            "profile_created": False,
        },
        substrate_status="PUBLIC_SDK_BUNDLE_EXPORTED_ONLY",
    )
    _write_receipt(receipt_out, receipt)
    return receipt


def _destination_state(
    profile: Path,
    payload: Mapping[str, Any],
    manifest: Path,
    manifest_sha256: str,
) -> tuple[str, dict[str, Any] | None, str | None]:
    overlay_relative, wheelhouse_relative = _manifest_relative_roots(payload)
    overlay = profile.joinpath(*overlay_relative.parts)
    wheelhouse = profile.joinpath(*wheelhouse_relative.parts)
    presence = [_lstat_or_none(path) is not None for path in (overlay, wheelhouse)]
    if not any(presence):
        return "ABSENT", None, None
    if not all(presence):
        present_component = "overlay" if presence[0] else "wheelhouse"
        missing_component = "wheelhouse" if presence[0] else "overlay"
        summary = _validate_sdk_component_exact(
            profile,
            payload,
            present_component,
        )
        return (
            f"PARTIAL_EXACT_{present_component.upper()}",
            {present_component: summary},
            missing_component,
        )
    try:
        validation = _validate_sdk_roots_exact(
            manifest,
            manifest_sha256,
            profile_root=profile,
        )
    except live_sdk_overlay.LiveSdkOverlayError as exc:
        raise LiveSdkPortabilityError("destination SDK installation conflicts") from exc
    return "EXACT", validation, None


def import_public_sdk_bundle(
    bundle_root: str | Path,
    *,
    confirmation: str,
    receipt_out: str | Path,
) -> dict[str, Any]:
    if confirmation != IMPORT_CONFIRMATION:
        raise LiveSdkPortabilityError("exact public SDK import confirmation is required")
    host = _host_evidence()
    bundle = validate_public_sdk_bundle(bundle_root)
    profile = _current_profile_root()
    payload = bundle["sdk_payload"]
    manifest = Path(bundle["sdk_manifest_path"])
    manifest_sha256 = str(bundle["sdk_manifest_sha256"])
    overlay_relative, wheelhouse_relative = _manifest_relative_roots(payload)
    _refuse_receipt_overlap(
        receipt_out,
        [
            Path(bundle["bundle_root"]),
            profile.joinpath(*overlay_relative.parts),
            profile.joinpath(*wheelhouse_relative.parts),
        ],
    )
    state, destination_validation, missing_component = _destination_state(
        profile, payload, manifest, manifest_sha256
    )
    profile_created = False
    created_profile_directories: list[Path] = []
    created_root_count = 0
    if state == "EXACT":
        result = "ALREADY_PRESENT_EXACT"
    else:
        _preflight_receipt_path(receipt_out, target_will_mutate=True)
        shared_parts = []
        for left, right in zip(overlay_relative.parts, wheelhouse_relative.parts):
            if left != right:
                break
            shared_parts.append(left)
        if not shared_parts:
            raise LiveSdkPortabilityError("SDK roots have no safe shared profile directory")
        component_relatives = {
            "overlay": overlay_relative,
            "wheelhouse": wheelhouse_relative,
        }
        components_to_publish = (
            ("overlay", "wheelhouse")
            if state == "ABSENT"
            else (str(missing_component),)
        )
        staging: Path | None = None
        preserve_staging = False
        installation_complete = False
        try:
            for component in components_to_publish:
                destination_parent = profile
                for path_component in component_relatives[component].parts[:-1]:
                    destination_parent /= path_component
                    if _lstat_or_none(destination_parent) is not None:
                        destination_parent = _absolute_existing_directory(
                            destination_parent,
                            label="SDK destination parent",
                        )
                    else:
                        destination_parent.mkdir()
                        created_profile_directories.append(destination_parent)
                        profile_created = True
            profile_ops = _absolute_existing_directory(
                profile.joinpath(*shared_parts),
                label="SDK shared destination parent",
            )
            staging = _new_staging(profile_ops, "international-live-sdk")
            source_profile = Path(bundle["profile_root"])
            staged_profile = staging / BUNDLE_PROFILE_NAME
            staged_profile.mkdir()
            staged_components: dict[str, dict[str, Any]] = {}
            for component in components_to_publish:
                relative = component_relatives[component]
                source = source_profile.joinpath(*relative.parts)
                target_parent = staged_profile
                for path_component in relative.parts[:-1]:
                    target_parent /= path_component
                    target_parent.mkdir(exist_ok=True)
                _copy_tree_new(source, target_parent / relative.name)
            for component in components_to_publish:
                staged_components[component] = _validate_sdk_component_exact(
                    staged_profile,
                    payload,
                    component,
                )
                staged_summary = dict(staged_components[component])
                bundle_summary = dict(bundle["sdk_validation"][component])
                staged_summary.pop("root", None)
                bundle_summary.pop("root", None)
                if staged_summary != bundle_summary:
                    raise LiveSdkPortabilityError(
                        f"staged {component} differs from the trusted bundle"
                    )
            if state.startswith("PARTIAL_EXACT_"):
                observed_state, observed_partial, observed_missing = (
                    _destination_state(
                        profile,
                        payload,
                        manifest,
                        manifest_sha256,
                    )
                )
                if (
                    observed_state != state
                    or observed_missing != missing_component
                    or observed_partial != destination_validation
                ):
                    raise LiveSdkPortabilityError(
                        "destination partial SDK changed before exact recovery"
                    )
            published: list[tuple[Path, Path]] = []
            try:
                for component in components_to_publish:
                    relative = component_relatives[component]
                    source = staged_profile.joinpath(*relative.parts)
                    destination = profile.joinpath(*relative.parts)
                    if _lstat_or_none(destination) is not None:
                        raise LiveSdkPortabilityError(
                            "SDK destination appeared during import"
                        )
                    _move_no_replace(source, destination)
                    published.append((destination, source))
                    created_root_count += 1
            except BaseException as exc:
                rollback_failures = _rollback_published_roots(published)
                if rollback_failures:
                    preserve_staging = True
                    raise LiveSdkPortabilityError(
                        "SDK import rollback failed; partial destination is blocked"
                    ) from exc
                raise
            try:
                destination_validation = _validate_sdk_roots_exact(
                    manifest,
                    manifest_sha256,
                    profile_root=profile,
                )
                for key in ("overlay", "wheelhouse"):
                    staged = dict(bundle["sdk_validation"][key])
                    destination = dict(destination_validation[key])
                    staged.pop("root", None)
                    destination.pop("root", None)
                    if staged != destination:
                        raise LiveSdkPortabilityError(
                            "imported SDK differs from the validated bundle"
                        )
            except BaseException as exc:
                rollback_failures = _rollback_published_roots(published)
                if rollback_failures:
                    preserve_staging = True
                    raise LiveSdkPortabilityError(
                        "SDK import validation rollback failed; partial destination "
                        "is blocked"
                    ) from exc
                raise
            installation_complete = True
        finally:
            if not preserve_staging:
                if staging is not None:
                    _remove_owned_staging_tree(staging)
                if not installation_complete:
                    for created_directory in reversed(
                        created_profile_directories
                    ):
                        if _lstat_or_none(created_directory) is not None:
                            if _is_reparse(created_directory):
                                raise LiveSdkPortabilityError(
                                    "SDK destination-parent cleanup refused a "
                                    "redirected entry"
                                )
                            created_directory.rmdir()
        result = (
            "CREATED"
            if state == "ABSENT"
            else "RECOVERED_EXACT_PARTIAL"
        )
    public_bundle = {key: value for key, value in bundle.items() if key != "sdk_payload"}
    receipt = _receipt(
        operation="import",
        result=result,
        host=host,
        evidence={
            "bundle": public_bundle,
            "destination_profile_root": str(profile),
            "destination_sdk_validation": destination_validation,
            "destination_initial_state": state,
            "recovered_missing_component": (
                missing_component if result == "RECOVERED_EXACT_PARTIAL" else None
            ),
            "publication_contract": {
                "atomic_single_root_publication": False,
                "destination_root_count": 2,
                "partial_destination_is_runtime_valid": False,
                "partial_destination_reuse_authorized": False,
                "partial_exact_recovery_authorized": True,
                "partial_changed_recovery_authorized": False,
                "partial_exact_recovery_mode": (
                    "CREATE_ONLY_MISSING_ROOT_AFTER_EXACT_REVALIDATION"
                ),
                "automatic_destination_overwrite_or_deletion_authorized": False,
            },
        },
        mutations={
            "bundle_created": False,
            "destination_parent_created": profile_created,
            "destination_sdk_roots_created": created_root_count > 0,
            "destination_sdk_root_count_created": created_root_count,
            "private_staging_directory_created": created_root_count > 0,
            "private_staging_directory_removed": created_root_count > 0,
            "partial_exact_recovery_performed": (
                result == "RECOVERED_EXACT_PARTIAL"
            ),
        },
        substrate_status="PUBLIC_SDK_SUBSTRATE_READY",
    )
    _write_receipt(receipt_out, receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit, export, or import the sealed public SDK without live authority."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit")
    audit.add_argument("--receipt-out", required=True)
    audit_source = audit.add_mutually_exclusive_group(required=True)
    audit_source.add_argument("--bundle-root")
    audit_source.add_argument("--manifest")
    audit.add_argument("--expected-manifest-sha256")
    audit.add_argument("--profile-root")
    export = subparsers.add_parser("export")
    export.add_argument("--manifest", required=True)
    export.add_argument("--expected-manifest-sha256", required=True)
    export.add_argument("--bundle-root", required=True)
    export.add_argument("--receipt-out", required=True)
    export.add_argument("--confirmation", required=True)
    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("--bundle-root", required=True)
    import_parser.add_argument("--receipt-out", required=True)
    import_parser.add_argument("--confirmation", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "audit":
            if args.bundle_root:
                if args.expected_manifest_sha256 or args.profile_root:
                    raise LiveSdkPortabilityError(
                        "bundle audit does not accept installed-profile arguments"
                    )
                receipt = audit_sdk_bundle(
                    args.bundle_root,
                    receipt_out=args.receipt_out,
                )
            else:
                if not args.expected_manifest_sha256:
                    raise LiveSdkPortabilityError(
                        "installed audit requires --expected-manifest-sha256"
                    )
                receipt = audit_installed_sdk(
                    args.manifest,
                    args.expected_manifest_sha256,
                    profile_root=args.profile_root,
                    receipt_out=args.receipt_out,
                )
        elif args.command == "export":
            receipt = export_public_sdk_bundle(
                args.manifest,
                args.expected_manifest_sha256,
                args.bundle_root,
                confirmation=args.confirmation,
                receipt_out=args.receipt_out,
            )
        else:
            receipt = import_public_sdk_bundle(
                args.bundle_root,
                confirmation=args.confirmation,
                receipt_out=args.receipt_out,
            )
    except (
        LiveSdkPortabilityError,
        live_sdk_overlay.LiveSdkOverlayError,
        OSError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema_version": RECEIPT_SCHEMA_VERSION,
                    "status": "BLOCK",
                    "error_type": type(exc).__name__,
                    "authority": NEGATIVE_AUTHORITY,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(_canonical_json_bytes(receipt).decode("ascii"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
