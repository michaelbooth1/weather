"""Windows path and ACL checks for fixed live-session artifacts."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import shutil
import stat
import subprocess
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
