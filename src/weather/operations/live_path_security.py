"""Windows path and ACL checks for fixed live-session artifacts."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import shutil
import stat
import subprocess
from collections.abc import Mapping, Sequence
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

if os.name == "nt":  # pragma: no cover - exercised by Windows operations tests.
    import winreg

from weather.execution_host import (
    CAPTURE_COLOCATED_HOST_PROFILE,
    EXECUTION_HOST_PROFILES,
    PORTABLE_EXECUTION_HOST_PROFILE,
    current_execution_host_id,
)


class LivePathSecurityError(RuntimeError):
    """Raised when a live-session path is redirected or broadly writable."""


NETWORK_REDIRECT_ENVIRONMENT_KEYS = frozenset(
    {
        "ALL_PROXY",
        "CURL_CA_BUNDLE",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
    }
)
MARKET_REGISTRY_OVERRIDE_ENVIRONMENT_KEY = "WEATHER_MARKET_REGISTRY"
MAX_PYVENV_CONFIG_BYTES = 16 * 1024
PYTHON_RUNTIME_BINDING_PAIRS = (
    ("interpreter_redirector", "interpreter_redirector_sha256"),
    ("pyvenv_config", "pyvenv_config_sha256"),
    ("runtime_process_image", "runtime_process_image_sha256"),
)


SESSION_BOOTSTRAP_PATHS = (
    "sitecustomize.py",
    "src/weather/__init__.py",
    "src/weather/paths.py",
    "src/weather/execution_host.py",
    "src/weather/schema_registry.py",
    "src/weather/schema_registry_data.py",
    "src/weather/schema_registry_recent_data.py",
    "src/weather/operations/__init__.py",
    "src/weather/operations/international_live_session_runner.py",
    "src/weather/operations/international_live_lineage.py",
    "src/weather/operations/international_live_time_window.py",
    "src/weather/operations/international_live_wrapper_sealer.py",
    "src/weather/operations/live_path_security.py",
)
STATUS_ATTESTATION_SOURCE_PATHS = (
    "scripts/ops/status.ps1",
    "scripts/ops/international_live_execution_host_status.ps1",
    "scripts/ops/integration_attempt_contract.ps1",
    "scripts/ops/streak_status.py", "src/weather/operations/settlement_hole_check.py",
    "src/weather/operations/documentation_transaction.py",
)



def repository_python_source_paths(root: str | Path) -> tuple[str, ...]:
    base = Path(root).resolve()
    return tuple(
        sorted(path.relative_to(base).as_posix() for path in (base / "src/weather").rglob("*.py"))
    )


def canonical_windows_powershell() -> Path:
    if os.name != "nt":
        raise LivePathSecurityError("canonical Windows PowerShell is Windows-only")
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if length <= 0 or length >= len(buffer):
        raise LivePathSecurityError("Windows system directory is unavailable")
    path = Path(buffer.value) / "WindowsPowerShell/v1.0/powershell.exe"
    return validate_regular_nonreparse_file(path)


def _same_resolved_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(
        str(right.resolve())
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_production_python_runtime_binding(
    production_root: str | Path,
    *,
    interpreter_redirector: str | Path | None = None,
) -> dict[str, str]:
    """Resolve and hash one canonical venv redirector/config/runtime chain."""

    root = validate_nonreparse_directory(production_root)
    expected_redirector = root / "venv/Scripts/python.exe"
    redirector = validate_regular_nonreparse_file(
        interpreter_redirector or expected_redirector
    )
    if not _same_resolved_path(redirector, expected_redirector):
        raise LivePathSecurityError(
            "production interpreter is not the canonical venv redirector"
        )
    config = validate_regular_nonreparse_file(root / "venv/pyvenv.cfg")
    try:
        raw = config.read_bytes()
    except OSError as exc:
        raise LivePathSecurityError(
            "production pyvenv configuration is unreadable"
        ) from exc
    if not raw or len(raw) > MAX_PYVENV_CONFIG_BYTES:
        raise LivePathSecurityError(
            "production pyvenv configuration size is invalid"
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise LivePathSecurityError(
            "production pyvenv configuration is not UTF-8"
        ) from exc
    required: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition("=")
        normalized_key = key.strip().casefold()
        if not separator or not normalized_key or not value.strip():
            raise LivePathSecurityError(
                "production pyvenv configuration is malformed"
            )
        if normalized_key not in {"home", "executable"}:
            continue
        if normalized_key in required:
            raise LivePathSecurityError(
                "production pyvenv configuration has duplicate identities"
            )
        required[normalized_key] = value.strip()
    if set(required) != {"home", "executable"}:
        raise LivePathSecurityError(
            "production pyvenv runtime identity is incomplete"
        )
    home_input = Path(required["home"])
    runtime_input = Path(required["executable"])
    if not home_input.is_absolute() or not runtime_input.is_absolute():
        raise LivePathSecurityError(
            "production pyvenv runtime identity is not absolute"
        )
    home = validate_nonreparse_directory(home_input)
    runtime = validate_regular_nonreparse_file(runtime_input)
    if not _same_resolved_path(runtime, home / "python.exe"):
        raise LivePathSecurityError(
            "production pyvenv runtime identity is inconsistent"
        )
    return {
        "interpreter_redirector": str(redirector),
        "interpreter_redirector_sha256": _sha256_file(redirector),
        "pyvenv_config": str(config),
        "pyvenv_config_sha256": hashlib.sha256(raw).hexdigest(),
        "runtime_process_image": str(runtime),
        "runtime_process_image_sha256": _sha256_file(runtime),
    }


def validate_production_python_runtime_binding(
    binding: object,
    *,
    production_root: str | Path | None = None,
) -> dict[str, str]:
    """Validate receipt fields as one current canonical Python runtime chain."""

    if not isinstance(binding, Mapping):
        raise LivePathSecurityError("production interpreter binding is invalid")
    redirector_input = Path(str(binding.get("interpreter_redirector") or ""))
    if not redirector_input.is_absolute():
        raise LivePathSecurityError("production interpreter binding is invalid")
    if production_root is None:
        if (
            redirector_input.parent.name.casefold() != "scripts"
            or redirector_input.parent.parent.name.casefold() != "venv"
        ):
            raise LivePathSecurityError(
                "production interpreter is not the canonical venv redirector"
            )
        production_root = redirector_input.parent.parent.parent
    current = resolve_production_python_runtime_binding(
        production_root,
        interpreter_redirector=redirector_input,
    )
    for path_key, hash_key in PYTHON_RUNTIME_BINDING_PAIRS:
        observed_path_input = Path(str(binding.get(path_key) or ""))
        observed_hash = str(binding.get(hash_key) or "")
        if not observed_path_input.is_absolute():
            raise LivePathSecurityError("production interpreter binding is invalid")
        observed_path = validate_regular_nonreparse_file(observed_path_input)
        if (
            not _same_resolved_path(observed_path, Path(current[path_key]))
            or observed_hash != current[hash_key]
        ):
            raise LivePathSecurityError(
                "production interpreter binding changed or is inconsistent"
            )
    return current


def validate_launcher_lease_process_lineage(
    *,
    lease_owner_pid: int,
    lease_path: str | Path,
    expected_owner_creation_time_token: str,
    expected_owner_executable: str | Path,
    expected_pyvenv_config: str | Path,
    expected_pyvenv_config_sha256: str,
    expected_redirector_executable: str | Path,
    expected_redirector_sha256: str,
    expected_runtime_executable: str | Path,
    expected_runtime_sha256: str,
    current_pid_reader=None,
    parent_pid_reader=None,
    process_observer=None,
    lease_active_probe=None,
) -> dict:
    """Prove that the live Python process descends from the lease owner.

    A Windows venv ``python.exe`` may be a redirector that starts the real
    interpreter.  The live wrapper therefore accepts either the lease-owning
    PowerShell process as its direct parent or exactly one intervening,
    hash-bound venv redirector.  Arbitrary ancestor depth is deliberately not
    accepted.
    """

    try:
        owner_pid = int(lease_owner_pid)
        current_pid = int((current_pid_reader or os.getpid)())
        direct_parent_pid = int((parent_pid_reader or os.getppid)())
    except (TypeError, ValueError) as exc:
        raise LivePathSecurityError("live launcher process identity is invalid") from exc
    if owner_pid <= 0 or current_pid <= 0 or direct_parent_pid <= 0:
        raise LivePathSecurityError("live launcher process identity is invalid")

    owner_executable = validate_regular_nonreparse_file(expected_owner_executable)
    pyvenv_config = validate_regular_nonreparse_file(expected_pyvenv_config)
    redirector_executable = validate_regular_nonreparse_file(
        expected_redirector_executable
    )
    runtime_executable = validate_regular_nonreparse_file(expected_runtime_executable)
    reviewed_lease_path = validate_regular_nonreparse_file(lease_path)
    owner_creation_token = str(expected_owner_creation_time_token or "")
    if not owner_creation_token.startswith("win32-filetime:") or not owner_creation_token[
        len("win32-filetime:") :
    ].isdigit():
        raise LivePathSecurityError("lease owner creation identity is invalid")
    active_probe = lease_active_probe or _windows_lease_file_is_deny_write_held
    if active_probe(reviewed_lease_path) is not True:
        raise LivePathSecurityError("live launcher lease handle is not active")
    def require_exact_hash(path: Path, expected: object, *, label: str) -> None:
        expected_hash = str(expected or "").lower()
        if (
            len(expected_hash) != 64
            or any(character not in "0123456789abcdef" for character in expected_hash)
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash
        ):
            raise LivePathSecurityError(f"sealed {label} hash changed")

    require_exact_hash(
        pyvenv_config,
        expected_pyvenv_config_sha256,
        label="live pyvenv configuration",
    )
    require_exact_hash(
        redirector_executable,
        expected_redirector_sha256,
        label="live Python redirector",
    )
    require_exact_hash(
        runtime_executable,
        expected_runtime_sha256,
        label="live Python runtime",
    )

    if process_observer is None:
        from weather.operations.supervisor import observe_process

        process_observer = observe_process

    def require_exact_process(pid: int, executable: Path, *, label: str) -> dict:
        observed = process_observer(pid)
        try:
            observed_pid = int(observed.get("pid"))
        except (AttributeError, TypeError, ValueError) as exc:
            raise LivePathSecurityError(
                f"{label} process identity is unavailable"
            ) from exc
        if (
            observed.get("state") != "running"
            or observed_pid != pid
            or observed.get("inspectable") is not True
            or not str(observed.get("creation_time_token") or "")
            or not str(observed.get("image_path") or "")
        ):
            raise LivePathSecurityError(f"{label} process identity is unavailable")
        observed_executable = validate_regular_nonreparse_file(
            str(observed["image_path"])
        )
        if observed_executable != executable:
            raise LivePathSecurityError(f"{label} process executable changed")
        return observed

    owner = require_exact_process(owner_pid, owner_executable, label="lease owner")
    runtime = require_exact_process(
        current_pid,
        runtime_executable,
        label="live Python runtime",
    )
    if str(owner.get("creation_time_token")) != owner_creation_token:
        raise LivePathSecurityError("lease owner process instance changed")
    try:
        observed_runtime_parent = int(runtime.get("parent_pid"))
    except (TypeError, ValueError) as exc:
        raise LivePathSecurityError(
            "live Python runtime parent is unavailable"
        ) from exc
    if observed_runtime_parent != direct_parent_pid:
        raise LivePathSecurityError("live Python runtime parent changed")

    def creation_ticks(observed: dict, *, label: str) -> int:
        token = str(observed.get("creation_time_token") or "")
        prefix = "win32-filetime:"
        if not token.startswith(prefix) or not token[len(prefix) :].isdigit():
            raise LivePathSecurityError(f"{label} creation identity is invalid")
        return int(token[len(prefix) :])

    owner_created = creation_ticks(owner, label="lease owner")
    runtime_created = creation_ticks(runtime, label="live Python runtime")
    relationship = "direct_lease_owner"
    redirector = None
    if direct_parent_pid != owner_pid:
        redirector = require_exact_process(
            direct_parent_pid,
            redirector_executable,
            label="live Python redirector",
        )
        try:
            redirector_owner_pid = int(redirector.get("parent_pid"))
        except (TypeError, ValueError) as exc:
            raise LivePathSecurityError(
                "live Python redirector parent is unavailable"
            ) from exc
        if redirector_owner_pid != owner_pid:
            raise LivePathSecurityError(
                "live Python redirector is not a direct child of the lease owner"
            )
        redirector_created = creation_ticks(
            redirector,
            label="live Python redirector",
        )
        if not owner_created < redirector_created < runtime_created:
            raise LivePathSecurityError("live launcher process creation order changed")
        relationship = "single_sealed_python_redirector"
    elif not owner_created < runtime_created:
        raise LivePathSecurityError("live launcher process creation order changed")

    def creation_token_hash(observed: dict) -> str:
        return hashlib.sha256(
            str(observed["creation_time_token"]).encode("utf-8")
        ).hexdigest()

    return {
        "status": "PASS",
        "relationship": relationship,
        "lease_owner_creation_token_sha256": creation_token_hash(owner),
        "redirector_creation_token_sha256": (
            creation_token_hash(redirector) if redirector is not None else None
        ),
        "runtime_creation_token_sha256": creation_token_hash(runtime),
    }


def launcher_lease_process_lineage_receipt_is_valid(value: object) -> bool:
    """Return whether one host attestation contains a complete lineage proof."""

    if not isinstance(value, dict):
        return False

    def is_sha256(candidate: object) -> bool:
        return bool(
            isinstance(candidate, str)
            and len(candidate) == 64
            and all(character in "0123456789abcdef" for character in candidate)
        )

    relationship = value.get("relationship")
    redirector_token_hash = value.get("redirector_creation_token_sha256")
    return bool(
        value.get("status") == "PASS"
        and relationship in {
            "direct_lease_owner",
            "single_sealed_python_redirector",
        }
        and is_sha256(value.get("lease_owner_creation_token_sha256"))
        and is_sha256(value.get("runtime_creation_token_sha256"))
        and (
            redirector_token_hash is None
            if relationship == "direct_lease_owner"
            else is_sha256(redirector_token_hash)
        )
    )


def launcher_host_attestations_have_consistent_lease_lineage(
    attestations: object,
) -> bool:
    """Require the same complete launcher lineage proof at all three checks."""

    if not isinstance(attestations, list) or len(attestations) != 3:
        return False
    lineage_rows = [
        row.get("lease_process_lineage") if isinstance(row, dict) else None
        for row in attestations
    ]
    if not all(
        launcher_lease_process_lineage_receipt_is_valid(row)
        for row in lineage_rows
    ):
        return False
    first = lineage_rows[0]
    return all(row == first for row in lineage_rows[1:])


def launcher_host_attestations_are_valid(
    attestations: object,
    *,
    expected_execution_host_profile: str,
    expected_execution_host_id: str,
    expected_status_flag_sha256: Sequence[str],
) -> bool:
    """Validate the complete three-row host-attestation contract."""

    if not launcher_host_attestations_have_consistent_lease_lineage(attestations):
        return False

    def is_sha256(candidate: object) -> bool:
        return bool(
            isinstance(candidate, str)
            and len(candidate) == 64
            and all(character in "0123456789abcdef" for character in candidate)
        )

    if (
        expected_execution_host_profile not in EXECUTION_HOST_PROFILES
        or not is_sha256(expected_execution_host_id)
        or isinstance(expected_status_flag_sha256, (str, bytes))
        or not isinstance(expected_status_flag_sha256, Sequence)
        or not all(is_sha256(value) for value in expected_status_flag_sha256)
    ):
        return False
    expected_flags = sorted(expected_status_flag_sha256)
    for row in attestations:
        flags = row.get("status_flag_sha256")
        checked_at = row.get("checked_at_local")
        if (
            not is_sha256(row.get("status_json_sha256"))
            or not isinstance(flags, list)
            or not all(is_sha256(value) for value in flags)
            or sorted(flags) != expected_flags
            or row.get("execution_host_profile")
            != expected_execution_host_profile
            or row.get("execution_host_id") != expected_execution_host_id
            or not isinstance(checked_at, str)
            or not checked_at
        ):
            return False
        try:
            timestamp = datetime.fromisoformat(checked_at)
        except ValueError:
            return False
        if timestamp.tzinfo is None:
            return False
    return True


def _windows_lease_file_is_deny_write_held(path: Path) -> bool:
    """Return true only for an active deny-write owner of the lease file."""

    if os.name != "nt":
        return False
    create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    handle = create_file(
        str(path),
        0x40000000,  # GENERIC_WRITE
        0x00000007,  # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
        None,
        3,  # OPEN_EXISTING
        0x00000080,  # FILE_ATTRIBUTE_NORMAL
        None,
    )
    if handle != ctypes.c_void_p(-1).value:
        close_handle(handle)
        return False
    return ctypes.get_last_error() == 32  # ERROR_SHARING_VIOLATION


def canonical_git_executable() -> Path:
    """Return the exact trusted Git executable for live public proofs."""

    if os.name == "nt":
        # Resolve the machine-wide Git for Windows installation without
        # trusting PATH or assuming that Windows is installed on C:. Invoke
        # the real payload directly: cmd\git.exe is only a launcher whose hash
        # does not bind the executable that performs repository operations.
        install_roots: set[Path] = set()
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\GitForWindows",
                    access=winreg.KEY_READ | view,
                ) as key:
                    value, value_type = winreg.QueryValueEx(key, "InstallPath")
            except OSError:
                continue
            if value_type != winreg.REG_SZ or not str(value).strip():
                raise LivePathSecurityError(
                    "machine-wide Git for Windows registration is invalid"
                )
            install_roots.add(Path(str(value).strip()))
        if len(install_roots) != 1:
            raise LivePathSecurityError(
                "one machine-wide Git for Windows installation is required"
            )
        path = next(iter(install_roots)) / "mingw64/bin/git.exe"
    else:  # Unit/static support; International live execution remains Windows-only.
        discovered = shutil.which("git")
        if not discovered:
            raise LivePathSecurityError("Git executable is absent")
        path = Path(discovered)
    return validate_regular_nonreparse_file(path)


def _windows_user_proxy_state() -> dict[str, bool]:
    if os.name != "nt":
        return {
            "proxy_enabled": False,
            "automatic_configuration": False,
            "automatic_detection": False,
        }

    class WinHttpCurrentUserIeProxyConfig(ctypes.Structure):
        _fields_ = (
            ("auto_detect", ctypes.c_int),
            ("auto_config_url", ctypes.c_void_p),
            ("proxy", ctypes.c_void_p),
            ("proxy_bypass", ctypes.c_void_p),
        )

    winhttp = ctypes.WinDLL("winhttp", use_last_error=True)
    query = winhttp.WinHttpGetIEProxyConfigForCurrentUser
    query.argtypes = (ctypes.POINTER(WinHttpCurrentUserIeProxyConfig),)
    query.restype = ctypes.c_int
    config = WinHttpCurrentUserIeProxyConfig()
    if not query(ctypes.byref(config)):
        raise LivePathSecurityError(
            "current-user Windows proxy configuration is unavailable"
        )
    global_free = ctypes.windll.kernel32.GlobalFree
    global_free.argtypes = (ctypes.c_void_p,)
    global_free.restype = ctypes.c_void_p

    def pointer_has_text(pointer) -> bool:
        return bool(pointer and ctypes.wstring_at(pointer).strip())

    try:
        return {
            "proxy_enabled": pointer_has_text(config.proxy)
            or pointer_has_text(config.proxy_bypass),
            "automatic_configuration": pointer_has_text(config.auto_config_url),
            "automatic_detection": bool(config.auto_detect),
        }
    finally:
        for pointer in (
            config.auto_config_url,
            config.proxy,
            config.proxy_bypass,
        ):
            if pointer:
                global_free(pointer)


def _windows_default_winhttp_proxy_is_direct() -> bool:
    if os.name != "nt":
        return True

    class WinHttpProxyInfo(ctypes.Structure):
        _fields_ = (
            ("access_type", ctypes.c_ulong),
            ("proxy", ctypes.c_void_p),
            ("proxy_bypass", ctypes.c_void_p),
        )

    winhttp = ctypes.WinDLL("winhttp", use_last_error=True)
    query = winhttp.WinHttpGetDefaultProxyConfiguration
    query.argtypes = (ctypes.POINTER(WinHttpProxyInfo),)
    query.restype = ctypes.c_int
    info = WinHttpProxyInfo()
    if not query(ctypes.byref(info)):
        raise LivePathSecurityError("default WinHTTP proxy configuration is unavailable")
    global_free = ctypes.windll.kernel32.GlobalFree
    global_free.argtypes = (ctypes.c_void_p,)
    global_free.restype = ctypes.c_void_p
    try:
        # WinHttpGetDefaultProxyConfiguration reports NO_PROXY (1) when the
        # machine-wide WinHTTP path is direct and NAMED_PROXY (3) otherwise.
        return info.access_type == 1 and not info.proxy
    finally:
        for pointer in (info.proxy, info.proxy_bypass):
            if pointer:
                global_free(pointer)


def assert_no_ambient_market_registry_override(
    *,
    environment: dict[str, str] | None = None,
) -> dict:
    """Refuse an untracked market-registry override at a live boundary."""

    source = os.environ if environment is None else environment
    configured = sorted(
        key.upper()
        for key, value in source.items()
        if key.upper() == MARKET_REGISTRY_OVERRIDE_ENVIRONMENT_KEY
        and str(value).strip()
    )
    if configured:
        raise LivePathSecurityError(
            "live-session process has an ambient market-registry override: "
            + ", ".join(configured)
        )
    return {
        "status": "PASS",
        "market_registry_override": False,
    }


def assert_no_ambient_proxy_configuration(
    *,
    environment: dict[str, str] | None = None,
    user_proxy_reader=None,
    winhttp_direct_reader=None,
) -> dict:
    """Fail closed if common process or Windows proxy controls are active."""

    source = os.environ if environment is None else environment
    assert_no_ambient_market_registry_override(environment=source)
    configured_environment_keys = sorted(
        key.upper()
        for key, value in source.items()
        if key.upper() in NETWORK_REDIRECT_ENVIRONMENT_KEYS and str(value).strip()
    )
    if configured_environment_keys:
        raise LivePathSecurityError(
            "live-session process has ambient proxy or TLS redirect variables: "
            + ", ".join(configured_environment_keys)
        )
    read_user_proxy = user_proxy_reader or _windows_user_proxy_state
    user_state = read_user_proxy()
    if set(user_state) != {
        "proxy_enabled",
        "automatic_configuration",
        "automatic_detection",
    } or any(value is not False for value in user_state.values()):
        raise LivePathSecurityError(
            "current-user Windows proxy or automatic proxy discovery is active"
        )
    read_winhttp_direct = (
        winhttp_direct_reader or _windows_default_winhttp_proxy_is_direct
    )
    if read_winhttp_direct() is not True:
        raise LivePathSecurityError("machine-wide WinHTTP proxy is active")
    return {
        "status": "PASS",
        "market_registry_override": False,
        "environment_proxy_variables": [],
        "current_user_proxy": "DIRECT",
        "winhttp_proxy": "DIRECT",
    }


def is_reparse(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _absolute_lexical(path: str | Path) -> Path:
    raw = os.fspath(path)
    if os.name == "nt":
        normalized = raw.replace("/", "\\")
        if normalized.startswith("\\\\") or normalized.startswith("\\??\\"):
            raise LivePathSecurityError(
                "live-session paths must use fixed or removable local media"
            )
    absolute = Path(os.path.abspath(raw))
    if os.name == "nt":
        root = absolute.anchor
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(str(root))
        if drive_type not in {2, 3}:  # DRIVE_REMOVABLE or DRIVE_FIXED
            raise LivePathSecurityError(
                "live-session paths must use fixed or removable local media"
            )
    return absolute


def _assert_no_reparse_components(path: Path) -> None:
    """Inspect the supplied path before ``resolve`` can erase a redirection."""

    absolute = _absolute_lexical(path)
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor /= part
        if cursor.exists() or cursor.is_symlink():
            if is_reparse(cursor):
                raise LivePathSecurityError("live-session path contains a redirected entry")
        else:
            break


def validate_regular_nonreparse_file(path: str | Path) -> Path:
    candidate_input = _absolute_lexical(path)
    _assert_no_reparse_components(candidate_input)
    try:
        candidate = candidate_input.resolve(strict=True)
    except OSError as exc:
        raise LivePathSecurityError("live-session artifact is absent") from exc
    if not candidate.is_file():
        raise LivePathSecurityError("live-session artifact is not a regular file")
    return candidate


def validate_nonreparse_directory(path: str | Path) -> Path:
    directory_input = _absolute_lexical(path)
    _assert_no_reparse_components(directory_input)
    try:
        directory = directory_input.resolve(strict=True)
    except OSError as exc:
        raise LivePathSecurityError("live-session directory is absent") from exc
    if not directory.is_dir():
        raise LivePathSecurityError("live-session path is not a directory")
    return directory


def validate_contained_regular_file(root: str | Path, path: str | Path) -> Path:
    base_input = _absolute_lexical(root)
    candidate_input = _absolute_lexical(path)
    try:
        candidate_input.relative_to(base_input)
    except ValueError as exc:
        raise LivePathSecurityError("live-session file escapes its attempt root") from exc
    _assert_no_reparse_components(base_input)
    _assert_no_reparse_components(candidate_input)
    base = base_input.resolve(strict=True)
    candidate = validate_regular_nonreparse_file(candidate_input)
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise LivePathSecurityError("live-session file resolves outside its attempt root") from exc
    return candidate


def validate_private_attempt_root(
    root: str | Path,
    *,
    powershell_path: str | Path | None = None,
) -> dict:
    """Require a non-reparse root with no broad write-capable ACL grants."""

    try:
        path = validate_nonreparse_directory(root)
    except LivePathSecurityError as exc:
        raise LivePathSecurityError("attempt root is absent or redirected") from exc
    powershell = Path(powershell_path or canonical_windows_powershell()).resolve()
    script = r"""
$ErrorActionPreference='Stop'
$path=$env:WEATHER_ATTEMPT_ROOT
$acl=[IO.Directory]::GetAccessControl($path)
$current=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$allowed=@($current,'S-1-5-18','S-1-5-32-544')
$danger=[Security.AccessControl.FileSystemRights]::Write -bor
  [Security.AccessControl.FileSystemRights]::Modify -bor
  [Security.AccessControl.FileSystemRights]::FullControl -bor
  [Security.AccessControl.FileSystemRights]::Delete -bor
  [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
  [Security.AccessControl.FileSystemRights]::TakeOwnership
$broad=@()
$currentWrite=$false
foreach($rule in $acl.Access){
  $sid=$rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
  $write=(($rule.FileSystemRights -band $danger) -ne 0)
  if($rule.AccessControlType -eq 'Allow' -and $write){
    if($sid -eq $current){$currentWrite=$true}
    if($sid -notin $allowed){$broad+=$sid}
  }
}
[pscustomobject]@{current_user_write=$currentWrite;broad_write_count=@($broad|Sort-Object -Unique).Count}|ConvertTo-Json -Compress
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        env={**os.environ, "WEATHER_ATTEMPT_ROOT": str(path)},
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise LivePathSecurityError("attempt-root ACL query failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise LivePathSecurityError("attempt-root ACL query was not JSON") from exc
    if (
        payload.get("current_user_write") is not True
        or payload.get("broad_write_count") != 0
    ):
        raise LivePathSecurityError("attempt root is broadly writable or not user-owned")
    return {
        "status": "PASS",
        "path": str(path),
        "current_user_write": True,
        "broad_write_count": 0,
        "reparse_point": False,
    }
