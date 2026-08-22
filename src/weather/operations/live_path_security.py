"""Windows path and ACL checks for fixed live-session artifacts."""

from __future__ import annotations

import base64
import json
import os
import stat
import subprocess
from pathlib import Path


class LivePathSecurityError(RuntimeError):
    """Raised when a live-session path is redirected or broadly writable."""


SESSION_BOOTSTRAP_PATHS = (
    "src/weather/__init__.py",
    "src/weather/paths.py",
    "src/weather/schema_registry.py",
    "src/weather/schema_registry_data.py",
    "src/weather/schema_registry_recent_data.py",
    "src/weather/operations/__init__.py",
    "src/weather/operations/international_live_session_runner.py",
    "src/weather/operations/international_live_lineage.py",
    "src/weather/operations/international_live_wrapper_sealer.py",
    "src/weather/operations/live_path_security.py",
)
STATUS_ATTESTATION_SOURCE_PATHS = (
    "scripts/ops/status.ps1", "scripts/ops/integration_attempt_contract.ps1",
    "scripts/ops/streak_status.py", "src/weather/operations/settlement_hole_check.py",
    "src/weather/operations/documentation_transaction.py",
)


def canonical_windows_powershell() -> Path:
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    path = (root / "System32/WindowsPowerShell/v1.0/powershell.exe").resolve()
    if not path.is_file():
        raise LivePathSecurityError("canonical Windows PowerShell is absent")
    return path


def is_reparse(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _absolute_lexical(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


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
$acl=Get-Acl -LiteralPath $path
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
