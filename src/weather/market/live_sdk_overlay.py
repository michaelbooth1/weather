"""Validate and process-locally activate the sealed International live SDK.

The shared production virtual environment remains unchanged.  Activation is
explicit, validates the complete external overlay and its offline wheelhouse,
and affects only the current process after every public hash check passes.
"""

from __future__ import annotations

import ctypes
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Mapping


MANIFEST_SCHEMA_VERSION = "international_live_sdk_overlay_manifest_v0.1"
EXPECTED_DISTRIBUTION = "polymarket-client"
EXPECTED_IMPORT_PACKAGE = "polymarket"
EXPECTED_VERSION = "0.6.0"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ACTIVATION: dict[str, Any] | None = None


class LiveSdkOverlayError(RuntimeError):
    """Raised when the sealed external SDK overlay does not match its manifest."""


def _require_local_windows_path(path: Path, *, label: str) -> None:
    if os.name != "nt":
        return
    normalized = str(path).replace("/", "\\")
    if normalized.startswith("\\\\") or re.fullmatch(r"[A-Za-z]:", path.drive) is None:
        raise LiveSdkOverlayError(f"{label} must be on a local Windows drive")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetDriveTypeW.restype = ctypes.c_uint
    if int(kernel32.GetDriveTypeW(path.drive + "\\")) not in {2, 3}:
        raise LiveSdkOverlayError(f"{label} must be on fixed or removable local media")


def _windows_token_profile_root() -> Path:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    advapi32.OpenProcessToken.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.OpenProcessToken.restype = ctypes.c_int
    userenv.GetUserProfileDirectoryW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    userenv.GetUserProfileDirectoryW.restype = ctypes.c_int
    token = ctypes.c_void_p()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)
    ):
        raise LiveSdkOverlayError("current Windows user token is unavailable")
    try:
        required = ctypes.c_ulong(0)
        userenv.GetUserProfileDirectoryW(token, None, ctypes.byref(required))
        if required.value <= 1:
            raise LiveSdkOverlayError("current Windows profile is unavailable")
        buffer = ctypes.create_unicode_buffer(required.value)
        if not userenv.GetUserProfileDirectoryW(
            token, buffer, ctypes.byref(required)
        ):
            raise LiveSdkOverlayError("current Windows profile is unavailable")
        return Path(buffer.value)
    finally:
        kernel32.CloseHandle(token)


def _reject_ambient_profile_conflict(profile: Path) -> None:
    expected = os.path.normcase(os.path.abspath(str(profile)))
    candidates = {
        "USERPROFILE": os.environ.get("USERPROFILE"),
        "HOME": os.environ.get("HOME"),
    }
    home_drive = os.environ.get("HOMEDRIVE")
    home_path = os.environ.get("HOMEPATH")
    if home_drive or home_path:
        candidates["HOMEDRIVE/HOMEPATH"] = (home_drive or "") + (home_path or "")
    for label, value in candidates.items():
        if not value:
            continue
        candidate = Path(value)
        if not candidate.is_absolute() or (
            os.path.normcase(os.path.abspath(str(candidate))) != expected
        ):
            raise LiveSdkOverlayError(
                f"ambient {label} conflicts with the current Windows token profile"
            )


def _profile_root() -> Path:
    if os.name != "nt":
        return Path.home().resolve()
    profile = _windows_token_profile_root()
    _require_local_windows_path(profile, label="current Windows profile")
    _reject_ambient_profile_conflict(profile)
    cursor = Path(profile.anchor)
    for part in profile.parts[1:]:
        cursor /= part
        try:
            redirected = _is_reparse(cursor)
        except FileNotFoundError:
            redirected = False
        if redirected:
            raise LiveSdkOverlayError(
                "current Windows profile contains a redirected entry"
            )
    resolved = profile.resolve()
    if not resolved.is_dir() or _is_reparse(resolved):
        raise LiveSdkOverlayError("current Windows profile is absent or redirected")
    return resolved


def current_live_sdk_profile_root() -> Path:
    """Return the OS-token-bound profile used for runtime SDK activation."""

    return _profile_root()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _exact_keys(value: Any, expected: set[str], *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise LiveSdkOverlayError(f"{label} does not have the exact manifest keys")
    return value


def _sha(value: Any, *, label: str) -> str:
    normalized = str(value or "").lower()
    if SHA256_RE.fullmatch(normalized) is None:
        raise LiveSdkOverlayError(f"{label} is not a SHA-256")
    return normalized


def _is_reparse(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _explicit_profile_root(profile_root: str | Path | None) -> Path:
    if profile_root is None:
        return _profile_root()
    raw = Path(profile_root)
    if not raw.is_absolute():
        raise LiveSdkOverlayError("explicit profile root must be absolute")
    _require_local_windows_path(raw, label="explicit profile root")
    cursor = Path(raw.anchor)
    for part in raw.parts[1:]:
        cursor /= part
        try:
            redirected = _is_reparse(cursor)
        except FileNotFoundError:
            redirected = False
        if redirected:
            raise LiveSdkOverlayError("explicit profile root contains a redirected entry")
    resolved = raw.resolve()
    if not resolved.is_dir() or _is_reparse(resolved):
        raise LiveSdkOverlayError("explicit profile root is absent or redirected")
    return resolved


def _resolve_profile_path(
    record: Mapping[str, Any],
    *,
    label: str,
    profile_root: str | Path | None = None,
) -> Path:
    if record.get("path_base") != "user_profile":
        raise LiveSdkOverlayError(f"{label} path base is unsupported")
    relative = Path(str(record.get("relative_path") or ""))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise LiveSdkOverlayError(f"{label} relative path is unsafe")
    profile = _explicit_profile_root(profile_root)
    unresolved = profile / relative
    cursor = profile
    for part in relative.parts:
        cursor /= part
        try:
            redirected = _is_reparse(cursor)
        except FileNotFoundError:
            redirected = False
        if redirected:
            raise LiveSdkOverlayError(f"{label} path contains a redirected entry")
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(profile)
    except ValueError as exc:
        raise LiveSdkOverlayError(f"{label} path escapes the user profile") from exc
    if not resolved.is_dir() or _is_reparse(resolved):
        raise LiveSdkOverlayError(f"{label} directory is absent or redirected")
    return resolved


def _validate_overlay(
    record: Mapping[str, Any],
    *,
    include_file_hashes: bool = False,
    profile_root: str | Path | None = None,
) -> dict[str, Any]:
    root = _resolve_profile_path(
        record,
        label="overlay",
        profile_root=profile_root,
    )
    for entry in root.rglob("*"):
        if _is_reparse(entry):
            raise LiveSdkOverlayError("overlay contains a redirected entry")
    files = sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    rows = []
    file_hashes = {}
    byte_count = 0
    for path in files:
        raw = path.read_bytes()
        byte_count += len(raw)
        digest = _sha256_bytes(raw)
        rows.append(f"{path.relative_to(root).as_posix()}:{len(raw)}:{digest}")
        file_hashes[str(path)] = digest
    aggregate = _sha256_bytes("\n".join(rows).encode("utf-8"))
    if (
        len(files) != int(record["file_count"])
        or byte_count != int(record["bytes"])
        or aggregate != _sha(record["tree_manifest_sha256"], label="overlay tree")
    ):
        raise LiveSdkOverlayError(
            "external SDK overlay tree changed "
            f"(files={len(files)}, bytes={byte_count}, sha256={aggregate})"
        )
    metadata_path = (root / str(record["metadata_relative_path"])).resolve()
    package_init = (root / str(record["package_init_relative_path"])).resolve()
    for path, expected, label in (
        (metadata_path, record["metadata_sha256"], "SDK metadata"),
        (package_init, record["package_init_sha256"], "SDK package init"),
    ):
        if root not in path.parents or not path.is_file() or _sha256_file(path) != _sha(
            expected, label=label
        ):
            raise LiveSdkOverlayError(f"{label} changed")
    metadata_text = metadata_path.read_text(encoding="utf-8")
    if "Name: polymarket-client\n" not in metadata_text.replace("\r\n", "\n") or (
        "Version: 0.6.0\n" not in metadata_text.replace("\r\n", "\n")
    ):
        raise LiveSdkOverlayError("SDK metadata does not prove polymarket-client 0.6.0")
    result = {
        "root": str(root),
        "file_count": len(files),
        "bytes": byte_count,
        "tree_manifest_sha256": aggregate,
        "metadata_sha256": _sha256_file(metadata_path),
        "package_init_sha256": _sha256_file(package_init),
    }
    if include_file_hashes:
        result["file_sha256"] = file_hashes
    return result


def _validate_wheelhouse(
    record: Mapping[str, Any],
    *,
    profile_root: str | Path | None = None,
) -> dict[str, Any]:
    root = _resolve_profile_path(
        record,
        label="wheelhouse",
        profile_root=profile_root,
    )
    entries = list(root.iterdir())
    if any(not path.is_file() or _is_reparse(path) or path.suffix.lower() != ".whl" for path in entries):
        raise LiveSdkOverlayError("wheelhouse contains a non-wheel or redirected entry")
    ordered_names = list(record["ordered_file_names"])
    if (
        len(ordered_names) != len(set(ordered_names))
        or set(ordered_names) != {path.name for path in entries}
    ):
        raise LiveSdkOverlayError("wheelhouse ordered filename manifest changed")
    entries_by_name = {path.name: path for path in entries}
    rows = []
    byte_count = 0
    hashes: dict[str, str] = {}
    for name in ordered_names:
        path = entries_by_name[name]
        digest = _sha256_file(path)
        byte_count += path.stat().st_size
        hashes[path.name] = digest
        rows.append(f"{path.name}:{digest.upper()}")
    aggregate = _sha256_bytes("\n".join(rows).encode("utf-8"))
    core_name = str(record["core_wheel_name"])
    if (
        len(entries) != int(record["file_count"])
        or byte_count != int(record["bytes"])
        or aggregate
        != _sha(record["name_hash_manifest_sha256"], label="wheelhouse manifest")
        or hashes.get(core_name)
        != _sha(record["core_wheel_sha256"], label="core wheel")
    ):
        raise LiveSdkOverlayError("offline SDK wheelhouse changed")
    return {
        "root": str(root),
        "file_count": len(entries),
        "bytes": byte_count,
        "name_hash_manifest_sha256": aggregate,
        "core_wheel_name": core_name,
        "core_wheel_sha256": hashes[core_name],
    }


def validate_live_sdk_overlay(
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    *,
    profile_root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate the exact public manifest, overlay tree, and wheelhouse.

    ``profile_root`` is a validation-only portability surface. Runtime
    activation deliberately does not expose it and remains bound to the
    current user's profile.
    """

    path = Path(manifest_path).resolve()
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveSdkOverlayError("SDK overlay manifest is unreadable") from exc
    expected_hash = _sha(expected_manifest_sha256, label="SDK overlay manifest")
    observed_hash = _sha256_bytes(raw)
    if observed_hash != expected_hash:
        raise LiveSdkOverlayError("SDK overlay manifest hash changed")
    manifest = _exact_keys(
        payload,
        {"schema_version", "distribution", "import_package", "version", "overlay", "wheelhouse"},
        label="SDK overlay manifest",
    )
    if (
        manifest["schema_version"] != MANIFEST_SCHEMA_VERSION
        or manifest["distribution"] != EXPECTED_DISTRIBUTION
        or manifest["import_package"] != EXPECTED_IMPORT_PACKAGE
        or manifest["version"] != EXPECTED_VERSION
    ):
        raise LiveSdkOverlayError("SDK overlay identity is not the pinned contract")
    overlay_record = _exact_keys(
        manifest["overlay"],
        {
            "path_base", "relative_path", "file_count", "bytes",
            "tree_manifest_sha256", "metadata_relative_path", "metadata_sha256",
            "package_init_relative_path", "package_init_sha256",
        },
        label="overlay",
    )
    wheelhouse_record = _exact_keys(
        manifest["wheelhouse"],
        {
            "path_base", "relative_path", "file_count", "bytes",
            "name_hash_manifest_sha256", "core_wheel_name", "core_wheel_sha256",
            "ordered_file_names",
        },
        label="wheelhouse",
    )
    return {
        "schema_version": "international_live_sdk_overlay_validation_v0.1",
        "status": "PASS",
        "manifest_path": str(path),
        "manifest_sha256": observed_hash,
        "distribution": EXPECTED_DISTRIBUTION,
        "version": EXPECTED_VERSION,
        "overlay": _validate_overlay(
            overlay_record,
            profile_root=profile_root,
        ),
        "wheelhouse": _validate_wheelhouse(
            wheelhouse_record,
            profile_root=profile_root,
        ),
        "process_path_activated": False,
        "shared_environment_mutated": False,
        "live_mutation_attempted": False,
        "credential_value_read": False,
    }


def validated_live_sdk_overlay_file_hashes(
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    *,
    profile_root: str | Path | None = None,
) -> dict[str, str]:
    """Return every validated lazy-import file identity for held-read locking."""

    validation = validate_live_sdk_overlay(
        manifest_path,
        expected_manifest_sha256,
        profile_root=profile_root,
    )
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8-sig"))
    overlay = _validate_overlay(
        payload["overlay"],
        include_file_hashes=True,
        profile_root=profile_root,
    )
    summary = {key: value for key, value in overlay.items() if key != "file_sha256"}
    if summary != validation["overlay"]:
        raise LiveSdkOverlayError("overlay changed while enumerating held files")
    return dict(overlay["file_sha256"])


def activate_live_sdk_overlay(
    manifest_path: str | Path,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    """Activate the validated overlay in this process only and prove its origin."""

    global _ACTIVATION
    runtime_profile = _profile_root()
    validation = validate_live_sdk_overlay(
        manifest_path,
        expected_manifest_sha256,
        profile_root=runtime_profile,
    )
    if _ACTIVATION is not None:
        if _ACTIVATION["manifest_sha256"] != validation["manifest_sha256"]:
            raise LiveSdkOverlayError("a different SDK overlay is already active")
        return dict(_ACTIVATION)
    if EXPECTED_IMPORT_PACKAGE in sys.modules or importlib.util.find_spec(
        EXPECTED_IMPORT_PACKAGE
    ) is not None:
        raise LiveSdkOverlayError("an ambient polymarket package is already importable")
    overlay_root = str(validation["overlay"]["root"])
    sys.path.insert(1 if sys.path else 0, overlay_root)
    sys.dont_write_bytecode = True
    importlib.invalidate_caches()
    try:
        package = importlib.import_module(EXPECTED_IMPORT_PACKAGE)
        distribution = importlib.metadata.distribution(EXPECTED_DISTRIBUTION)
        package_path = Path(str(package.__file__)).resolve()
        distribution_path = Path(distribution.locate_file("")).resolve()
        root = Path(overlay_root).resolve()
        if (
            root not in package_path.parents
            or root != distribution_path
            or str(package.__version__) != EXPECTED_VERSION
            or str(distribution.version) != EXPECTED_VERSION
        ):
            raise LiveSdkOverlayError("activated SDK did not resolve from the sealed overlay")
        post_import = validate_live_sdk_overlay(
            manifest_path,
            expected_manifest_sha256,
            profile_root=runtime_profile,
        )
        if (
            post_import["overlay"] != validation["overlay"]
            or post_import["wheelhouse"] != validation["wheelhouse"]
        ):
            raise LiveSdkOverlayError("SDK overlay changed across import activation")
    except BaseException:
        sys.path = [entry for entry in sys.path if os.path.normcase(entry) != os.path.normcase(overlay_root)]
        sys.modules.pop(EXPECTED_IMPORT_PACKAGE, None)
        importlib.invalidate_caches()
        raise
    validation.update(
        {
            "process_path_activated": True,
            "package_path": str(package_path),
            "distribution_path": str(distribution_path),
            "post_import_revalidation": "PASS",
        }
    )
    _ACTIVATION = validation
    return dict(validation)
