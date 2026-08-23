"""Prepare one no-argument launcher for a reviewed fixed live-session manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from weather.operations import international_live_wrapper_sealer as fixed_sealer
from weather.operations.international_live_session_runner import (
    MAX_SESSION_SECONDS,
    SESSION_SCHEMA_VERSION,
    SESSION_BOOTSTRAP_PATHS,
    _canonical_payload_sha256,
)
from weather.operations.international_live_wrapper_sealer import (
    _canonical_json,
    _default_powershell_parser,
    _write_new,
)
from weather.operations.live_path_security import (
    canonical_windows_powershell,
    validate_contained_regular_file,
    validate_nonreparse_directory,
    validate_private_attempt_root,
    validate_regular_nonreparse_file,
)
from weather.paths import REPO_ROOT
from weather.schema_registry import schema_version


TEMPLATE_PATH = (
    REPO_ROOT
    / "scripts/ops/international_live_templates/fixed_session_launcher.ps1.tmpl"
)
RUNNER_SOURCE = REPO_ROOT / "src/weather/operations/international_live_session_runner.py"
MANIFEST_BUILD_SCHEMA_VERSION = schema_version(
    "international_live_session_manifest_build"
)
FIXED_SESSION_BUDGET_PUSD = Decimal("10")
FIXED_SESSION_SECONDS = MAX_SESSION_SECONDS
ATTEMPT_DIRECTORIES = ("inputs", "incoming", "session")
STAGED_INPUT_LAYOUTS = {
    "stage0": {
        "identity": "inputs/stage0-identity.json",
        "credential_import_receipt": (
            "inputs/stage0-credential-import-receipt.json"
        ),
        "credential_reference_manifest": (
            "inputs/stage0-credential-reference-manifest.json"
        ),
        "discovery_plan": "inputs/stage0-discovery-plan.json",
        "reviewed_status_flags": "inputs/stage0-reviewed-status-flags.json",
        "build_receipt": "inputs/stage0-session-manifest-build-receipt.json",
    },
    "stage1_cancel_all": {
        "identity": "inputs/stage1-identity.json",
        "credential_import_receipt": (
            "inputs/stage1-cancel-all-credential-import-receipt.json"
        ),
        "credential_reference_manifest": (
            "inputs/stage1-cancel-all-credential-reference-manifest.json"
        ),
        "discovery_plan": "inputs/stage1-cancel-all-discovery-plan.json",
        "reviewed_status_flags": (
            "inputs/stage1-cancel-all-reviewed-status-flags.json"
        ),
        "build_receipt": (
            "inputs/stage1-cancel-all-session-manifest-build-receipt.json"
        ),
    },
    "stage1_dead_man": {
        "identity": "inputs/stage1-dead-man-identity.json",
        "credential_import_receipt": (
            "inputs/stage1-dead-man-credential-import-receipt.json"
        ),
        "credential_reference_manifest": (
            "inputs/stage1-dead-man-credential-reference-manifest.json"
        ),
        "discovery_plan": "inputs/stage1-dead-man-discovery-plan.json",
        "reviewed_status_flags": (
            "inputs/stage1-dead-man-reviewed-status-flags.json"
        ),
        "build_receipt": (
            "inputs/stage1-dead-man-session-manifest-build-receipt.json"
        ),
    },
}


class SessionLauncherSealError(RuntimeError):
    """Raised when a reviewed fixed-session launcher cannot be prepared."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(
        str(right.resolve())
    )


def _is_within(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _require_exact_object(
    value: Any,
    keys: set[str],
    *,
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise SessionLauncherSealError(f"{label} does not have exact keys")
    return value


def _require_sha256(value: Any, *, label: str) -> str:
    digest = str(value or "").lower()
    if fixed_sealer.SHA256_RE.fullmatch(digest) is None:
        raise SessionLauncherSealError(f"{label} is not a lowercase SHA-256")
    return digest


def _read_json_object(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SessionLauncherSealError(f"{label} is unreadable") from exc
    if not isinstance(payload, dict):
        raise SessionLauncherSealError(f"{label} is not a JSON object")
    return payload, raw


def _read_stable_public_source(path: str | Path, *, label: str) -> tuple[Path, bytes, str]:
    source = validate_regular_nonreparse_file(path)
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if _sha(source) != digest:
        raise SessionLauncherSealError(f"{label} changed while it was read")
    return source, raw, digest


def _default_attempt_directory_creator(root: Path) -> None:
    """Create one new Windows directory with a protected inheritable ACL."""

    if os.name != "nt":
        raise SessionLauncherSealError(
            "private live-session attempt initialization is Windows-only"
        )
    script = r"""
$ErrorActionPreference='Stop'
$path=$env:WEATHER_NEW_ATTEMPT_ROOT
if([string]::IsNullOrWhiteSpace($path)){throw 'attempt root is absent'}
if(Test-Path -LiteralPath $path){throw 'attempt root already exists'}
$current=[Security.Principal.WindowsIdentity]::GetCurrent().User
$acl=New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true,$false)
$acl.SetOwner($current)
$inherit=[Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
$propagate=[Security.AccessControl.PropagationFlags]::None
foreach($sidText in @($current.Value,'S-1-5-18','S-1-5-32-544')){
  $sid=New-Object Security.Principal.SecurityIdentifier($sidText)
  $rule=New-Object Security.AccessControl.FileSystemAccessRule(
    $sid,
    [Security.AccessControl.FileSystemRights]::FullControl,
    $inherit,
    $propagate,
    [Security.AccessControl.AccessControlType]::Allow
  )
  [void]$acl.AddAccessRule($rule)
}
[void][IO.Directory]::CreateDirectory($path,$acl)
foreach($name in @('inputs','incoming','session')){
  [void][IO.Directory]::CreateDirectory((Join-Path $path $name))
}
"""
    environment = os.environ.copy()
    environment["WEATHER_NEW_ATTEMPT_ROOT"] = str(root)
    result = subprocess.run(
        [
            str(canonical_windows_powershell()),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SessionLauncherSealError(
            "private live-session attempt directory creation failed"
        )


def initialize_private_attempt_root(
    attempt_root: str | Path,
    *,
    production_root: str | Path = REPO_ROOT,
    directory_creator: Callable[[Path], None] = _default_attempt_directory_creator,
    attempt_root_validator=validate_private_attempt_root,
) -> dict[str, Any]:
    """Create and validate one external, private, never-reused attempt root."""

    requested = Path(attempt_root)
    if not requested.is_absolute():
        raise SessionLauncherSealError("attempt root must be absolute")
    root = Path(os.path.abspath(os.fspath(requested)))
    production = validate_nonreparse_directory(production_root)
    if _same_path(root, production) or _is_within(production, root):
        raise SessionLauncherSealError(
            "attempt root must be outside the production repository"
        )
    if root.exists() or root.is_symlink():
        raise SessionLauncherSealError("attempt root namespace is already spent")
    parent = validate_nonreparse_directory(root.parent)
    if not _same_path(parent, root.parent):
        raise SessionLauncherSealError("attempt root parent is not canonical")
    directory_creator(root)
    root = validate_nonreparse_directory(root)
    security = dict(attempt_root_validator(root))
    if security.get("status") != "PASS":
        raise SessionLauncherSealError(
            "attempt root security validation did not pass"
        )
    directories: dict[str, str] = {}
    for name in ATTEMPT_DIRECTORIES:
        directory = validate_nonreparse_directory(root / name)
        if not _is_within(root, directory):
            raise SessionLauncherSealError("attempt directory escapes its root")
        child_security = dict(attempt_root_validator(directory))
        if child_security.get("status") != "PASS":
            raise SessionLauncherSealError(
                "attempt child-directory security validation did not pass"
            )
        directories[name] = str(directory)
    return {
        "status": "PASS",
        "attempt_root": str(root),
        "directories": directories,
        "security": security,
        "live_mutation_attempted": False,
        "credential_values_read_in_memory": False,
    }


def _validate_public_inventory(
    stage: str,
    production_root: Path,
    inventory: Mapping[str, Any],
    *,
    git_state_validator: Callable[[Mapping[str, Any]], Any] | None,
) -> dict[str, Any]:
    _require_exact_object(
        inventory,
        {
            "schema_version",
            "status",
            "stage",
            "production",
            "template_sha256",
            "source_sha256",
            "session_bootstrap_sha256",
            "live_mutation_attempted",
            "credential_value_read",
        },
        label="public inventory",
    )
    if not all(
        (
            inventory["schema_version"] == fixed_sealer.INVENTORY_SCHEMA_VERSION,
            inventory["status"] == "PASS",
            inventory["stage"] == stage,
            inventory["live_mutation_attempted"] is False,
            inventory["credential_value_read"] is False,
        )
    ):
        raise SessionLauncherSealError("public inventory did not pass exactly")
    production = _require_exact_object(
        inventory["production"],
        {
            "root",
            "branch",
            "commit",
            "tree",
            "object_format",
            "python",
            "python_sha256",
            "interrupt_cleanup_ancestor_integrated",
        },
        label="public inventory production",
    )
    root = validate_nonreparse_directory(str(production["root"]))
    python = validate_regular_nonreparse_file(str(production["python"]))
    expected_python = (root / "venv/Scripts/python.exe").resolve()
    object_format = str(production["object_format"] or "")
    oid_length = {"sha1": 40, "sha256": 64}.get(object_format)
    commit = str(production["commit"] or "").lower()
    tree = str(production["tree"] or "").lower()
    python_hash = _require_sha256(
        production["python_sha256"], label="production interpreter hash"
    )
    if not all(
        (
            _same_path(root, production_root),
            production["branch"] == "master",
            production["interrupt_cleanup_ancestor_integrated"] is True,
            oid_length is not None,
            fixed_sealer.GIT_OID_RE.fullmatch(commit) is not None,
            fixed_sealer.GIT_OID_RE.fullmatch(tree) is not None,
            len(commit) == oid_length,
            len(tree) == oid_length,
            _same_path(python, expected_python),
            _sha(python) == python_hash,
        )
    ):
        raise SessionLauncherSealError("public inventory production is not canonical")
    production_record = {
        "root": str(root),
        "branch": "master",
        "commit": commit,
        "tree": tree,
        "python": str(python),
    }
    if git_state_validator is None:
        fixed_sealer._verify_git_state(
            production_record,
            git_runner=fixed_sealer._default_git_runner,
        )
    else:
        git_state_validator(production_record)

    templates = _require_exact_object(
        inventory["template_sha256"],
        {"python", "launcher"},
        label="public inventory template hashes",
    )
    template_paths = {
        "python": root / fixed_sealer.PYTHON_TEMPLATE_PATHS[stage],
        "launcher": root / fixed_sealer.LAUNCHER_TEMPLATE_PATH,
    }
    normalized_templates: dict[str, str] = {}
    for role, path in template_paths.items():
        path = validate_regular_nonreparse_file(path)
        digest = _require_sha256(templates[role], label=f"template hash {role}")
        if _sha(path) != digest:
            raise SessionLauncherSealError("public inventory template hash changed")
        normalized_templates[role] = digest

    expected_sources = set(fixed_sealer.LIVE_SOURCE_PATHS[stage]) | {
        fixed_sealer.WORKLOAD_ADMISSION_PATH
    }
    sources = _require_exact_object(
        inventory["source_sha256"],
        expected_sources,
        label="public inventory source hashes",
    )
    normalized_sources: dict[str, str] = {}
    for relative in sorted(expected_sources):
        path = validate_regular_nonreparse_file(root / relative)
        digest = _require_sha256(
            sources[relative], label=f"source hash {relative}"
        )
        if _sha(path) != digest:
            raise SessionLauncherSealError(
                f"public inventory source hash changed: {relative}"
            )
        normalized_sources[relative] = digest

    bootstrap = _require_exact_object(
        inventory["session_bootstrap_sha256"],
        set(SESSION_BOOTSTRAP_PATHS),
        label="public inventory session bootstrap hashes",
    )
    normalized_bootstrap: dict[str, str] = {}
    for relative in SESSION_BOOTSTRAP_PATHS:
        path = validate_regular_nonreparse_file(root / relative)
        digest = _require_sha256(
            bootstrap[relative], label=f"session bootstrap hash {relative}"
        )
        if _sha(path) != digest:
            raise SessionLauncherSealError(
                f"public inventory session bootstrap hash changed: {relative}"
            )
        normalized_bootstrap[relative] = digest
    return {
        "production": production_record,
        "production_python_sha256": python_hash,
        "template_sha256": dict(sorted(normalized_templates.items())),
        "source_sha256": dict(sorted(normalized_sources.items())),
        "session_bootstrap_sha256": dict(sorted(normalized_bootstrap.items())),
    }


def _parse_aware_utc(value: Any, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise SessionLauncherSealError(f"{label} is not a timestamp") from exc
    if parsed.tzinfo is None:
        raise SessionLauncherSealError(f"{label} is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _validate_discovery_plan(
    path: Path,
    *,
    now: datetime,
) -> dict[str, str]:
    payload, raw = _read_json_object(path, label="discovery plan")
    selected = payload.get("selected")
    policy = payload.get("selection_policy")
    if not isinstance(selected, dict) or not isinstance(policy, dict):
        raise SessionLauncherSealError("discovery plan has no selected public scope")
    expected_scope = policy.get("expected_bootstrap_scope")
    if not isinstance(expected_scope, dict) or set(expected_scope) != {
        "condition_id",
        "token_id",
    }:
        raise SessionLauncherSealError(
            "discovery plan expected-bootstrap scope is malformed"
        )
    created = _parse_aware_utc(payload.get("created_at_utc"), label="plan creation")
    expires = _parse_aware_utc(payload.get("expires_at_utc"), label="plan expiry")
    current = now.astimezone(timezone.utc)
    condition = str(selected.get("condition_id") or "").lower()
    token = str(selected.get("token_id") or "")
    target = str(payload.get("target_date") or "")
    try:
        canonical_target = date.fromisoformat(target).isoformat()
    except ValueError as exc:
        raise SessionLauncherSealError("discovery target date is invalid") from exc
    semantic_hash = _require_sha256(
        payload.get("plan_sha256"), label="discovery semantic hash"
    )
    observed_semantic_hash = fixed_sealer._canonical_payload_sha256(
        payload, omit="plan_sha256"
    )
    paper = selected.get("paper_quote_proof")
    if not isinstance(paper, dict):
        raise SessionLauncherSealError("discovery plan has no paper quote proof")
    paper_generated = _parse_aware_utc(
        paper.get("generated_at_utc"), label="paper quote creation"
    )
    paper_expires = _parse_aware_utc(
        paper.get("expires_at_utc"), label="paper quote expiry"
    )
    try:
        paper_ttl = Decimal(str(paper.get("quote_ttl_seconds")))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SessionLauncherSealError("paper quote TTL is invalid") from exc
    expected_paper_expiry = paper_generated + timedelta(seconds=float(paper_ttl))
    expected_expiry = min(
        created + timedelta(seconds=fixed_sealer.MAX_CANDIDATE_AGE_SECONDS),
        paper_expires,
    )
    if not all(
        (
            payload.get("schema_version") == fixed_sealer.CANDIDATE_SCHEMA_VERSION,
            payload.get("status") == "PASS",
            payload.get("platform") == "polymarket_global",
            payload.get("settlement_unit") == "pUSD",
            payload.get("selection_is_trading_authorization") is False,
            payload.get("secret_values_retained") is False,
            semantic_hash == observed_semantic_hash,
            created <= current <= expires,
            paper_generated <= created,
            Decimal("0") < paper_ttl <= fixed_sealer.MAX_PAPER_QUOTE_TTL_SECONDS,
            paper_expires == expected_paper_expiry,
            expires == expected_expiry,
            canonical_target == target,
            fixed_sealer.CONDITION_RE.fullmatch(condition) is not None,
            fixed_sealer.TOKEN_RE.fullmatch(token) is not None,
            expected_scope["condition_id"] is None,
            expected_scope["token_id"] is None,
            str(paper.get("condition_id") or "").lower() == condition,
            str(paper.get("token_id") or "") == token,
        )
    ):
        raise SessionLauncherSealError(
            "discovery plan is not a current, unconstrained, non-authorizing PASS"
        )
    return {
        "target_date": target,
        "condition_id": condition,
        "token_id": token,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "semantic_sha256": semantic_hash,
        "expires_at_utc": expires.isoformat(),
    }


def _load_reviewed_status_flags(path: Path) -> list[dict[str, str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SessionLauncherSealError(
            "reviewed-status-flags JSON is unreadable"
        ) from exc
    if not isinstance(payload, list):
        raise SessionLauncherSealError(
            "reviewed-status-flags JSON must be a list"
        )
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(payload):
        row = _require_exact_object(
            item,
            {"sha256", "review"},
            label=f"reviewed status flag {index}",
        )
        digest = _require_sha256(
            row["sha256"], label=f"reviewed status flag {index} hash"
        )
        review = str(row["review"] or "").strip()
        if not 12 <= len(review) <= 500:
            raise SessionLauncherSealError(
                "each reviewed status flag needs a concise written review"
            )
        normalized.append({"sha256": digest, "review": review})
    normalized.sort(key=lambda row: row["sha256"])
    if len({row["sha256"] for row in normalized}) != len(normalized):
        raise SessionLauncherSealError(
            "reviewed status flag hashes are not unique"
        )
    return normalized


def _assert_unique_workload(attempt_root: Path, workload: str) -> None:
    if fixed_sealer.WORKLOAD_RE.fullmatch(workload) is None:
        raise SessionLauncherSealError("lease workload name is invalid")
    for stage in fixed_sealer.STAGES:
        manifest_path = (
            attempt_root / "inputs" / f"{stage}-session-manifest.json"
        )
        if not manifest_path.exists():
            continue
        path = validate_contained_regular_file(attempt_root, manifest_path)
        payload, _raw = _read_json_object(path, label="existing session manifest")
        scope = payload.get("scope")
        if not isinstance(scope, dict) or not scope.get("lease_workload"):
            raise SessionLauncherSealError(
                "existing session manifest cannot prove workload uniqueness"
            )
        if str(scope["lease_workload"]) == workload:
            raise SessionLauncherSealError(
                "lease workload is already bound in this attempt"
            )


def prepare_fixed_session_manifest(
    *,
    stage: str,
    discovery_plan_path: str | Path,
    identity_source_path: str | Path,
    credential_import_receipt_source_path: str | Path,
    credential_reference_manifest_source_path: str | Path,
    attempt_root: str | Path,
    lease_workload: str,
    reviewed_status_flags_path: str | Path | None = None,
    production_root: str | Path = REPO_ROOT,
    now: datetime | None = None,
    inventory_builder=fixed_sealer.build_public_inventory,
    git_state_validator: Callable[[Mapping[str, Any]], Any] | None = None,
    attempt_root_validator=validate_private_attempt_root,
) -> dict[str, Any]:
    """Build one fixed-session manifest from current public, reviewed inputs."""

    if stage not in fixed_sealer.STAGES:
        raise SessionLauncherSealError("session manifest stage is unsupported")
    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        raise SessionLauncherSealError("session manifest clock is not timezone-aware")
    root_input = Path(attempt_root)
    if not root_input.is_absolute():
        raise SessionLauncherSealError("attempt root must be absolute")
    root = validate_nonreparse_directory(root_input)
    production = validate_nonreparse_directory(production_root)
    if _same_path(root, production) or _is_within(production, root):
        raise SessionLauncherSealError(
            "attempt root must be outside the production repository"
        )
    root_security = dict(attempt_root_validator(root))
    if root_security.get("status") != "PASS":
        raise SessionLauncherSealError(
            "attempt root security validation did not pass"
        )
    for name in ATTEMPT_DIRECTORIES:
        directory = validate_nonreparse_directory(root / name)
        if not _is_within(root, directory):
            raise SessionLauncherSealError("attempt directory escapes its root")
        if dict(attempt_root_validator(directory)).get("status") != "PASS":
            raise SessionLauncherSealError(
                "attempt child-directory security validation did not pass"
            )
    _assert_unique_workload(root, str(lease_workload))

    inventory = inventory_builder(stage, production)
    reviewed_inventory = _validate_public_inventory(
        stage,
        production,
        inventory,
        git_state_validator=git_state_validator,
    )
    layout = STAGED_INPUT_LAYOUTS[stage]
    source_arguments = {
        "identity": identity_source_path,
        "credential_import_receipt": credential_import_receipt_source_path,
        "credential_reference_manifest": credential_reference_manifest_source_path,
        "discovery_plan": discovery_plan_path,
    }
    staged: dict[str, dict[str, Any]] = {}
    pending_writes: list[tuple[Path, bytes]] = []
    destinations: set[str] = set()
    for role, source_argument in source_arguments.items():
        source, raw, digest = _read_stable_public_source(
            source_argument, label=role.replace("_", " ")
        )
        if _same_path(source, production) or _is_within(production, source):
            raise SessionLauncherSealError(
                "public input source must be outside the production repository"
            )
        destination = (root / layout[role]).resolve()
        if not _is_within(root, destination):
            raise SessionLauncherSealError("staged public input escapes attempt root")
        if _same_path(source, destination):
            raise SessionLauncherSealError(
                "public input source must be distinct from its new canonical copy"
            )
        normalized_destination = os.path.normcase(str(destination))
        if normalized_destination in destinations or destination.exists():
            raise SessionLauncherSealError(
                "canonical staged-input namespace is already spent"
            )
        destinations.add(normalized_destination)
        staged[role] = {
            "source_path": str(source),
            "path": str(destination),
            "sha256": digest,
            "bytes": len(raw),
        }
        pending_writes.append((destination, raw))

    discovery = _validate_discovery_plan(
        Path(staged["discovery_plan"]["source_path"]), now=current
    )
    if discovery["sha256"] != staged["discovery_plan"]["sha256"]:
        raise SessionLauncherSealError("discovery plan changed during validation")
    reference_payload = fixed_sealer._validate_credential_reference_manifest(
        Path(staged["credential_reference_manifest"]["source_path"])
    )
    fixed_sealer._validate_credential_import_receipt(
        Path(staged["credential_import_receipt"]["source_path"])
    )
    fixed_sealer._validate_identity(
        Path(staged["identity"]["source_path"]),
        requested_budget=FIXED_SESSION_BUDGET_PUSD,
        expected_reference=reference_payload,
    )

    reviewed_status_flags: list[dict[str, str]] = []
    if reviewed_status_flags_path is not None:
        source, raw, digest = _read_stable_public_source(
            reviewed_status_flags_path,
            label="reviewed status flags",
        )
        destination = (root / layout["reviewed_status_flags"]).resolve()
        normalized_destination = os.path.normcase(str(destination))
        if not _is_within(root, destination):
            raise SessionLauncherSealError(
                "reviewed-status-flags copy escapes attempt root"
            )
        if _same_path(source, production) or _is_within(production, source):
            raise SessionLauncherSealError(
                "reviewed-status-flags source must be outside production"
            )
        if (
            _same_path(source, destination)
            or normalized_destination in destinations
            or destination.exists()
        ):
            raise SessionLauncherSealError(
                "canonical reviewed-status-flags namespace is already spent"
            )
        destinations.add(normalized_destination)
        reviewed_status_flags = _load_reviewed_status_flags(source)
        staged["reviewed_status_flags"] = {
            "source_path": str(source),
            "path": str(destination),
            "sha256": digest,
            "bytes": len(raw),
        }
        pending_writes.append((destination, raw))

    manifest_path = (root / "inputs" / f"{stage}-session-manifest.json").resolve()
    sidecar_path = manifest_path.with_suffix(manifest_path.suffix + ".sha256")
    build_receipt_path = (root / layout["build_receipt"]).resolve()
    if any(
        path.exists()
        for path in (manifest_path, sidecar_path, build_receipt_path)
    ):
        raise SessionLauncherSealError(
            "session manifest build namespace is already spent"
        )
    manifest: dict[str, Any] = {
        "schema_version": SESSION_SCHEMA_VERSION,
        "stage": stage,
        "production": reviewed_inventory["production"],
        "scope": {
            "target_date": discovery["target_date"],
            "condition_id": discovery["condition_id"],
            "token_id": discovery["token_id"],
            "requested_budget_pusd": int(FIXED_SESSION_BUDGET_PUSD),
            "attempt_root": str(root),
            "lease_workload": str(lease_workload),
            "max_session_seconds": FIXED_SESSION_SECONDS,
        },
        "inputs": {
            role: {
                "path": staged[role]["path"],
                "sha256": staged[role]["sha256"],
            }
            for role in (
                "identity",
                "credential_import_receipt",
                "credential_reference_manifest",
            )
        },
        "reviewed_status_flags": reviewed_status_flags,
        "template_sha256": reviewed_inventory["template_sha256"],
        "source_sha256": reviewed_inventory["source_sha256"],
        "production_python_sha256": reviewed_inventory[
            "production_python_sha256"
        ],
        "session_bootstrap_sha256": reviewed_inventory[
            "session_bootstrap_sha256"
        ],
    }
    manifest["manifest_sha256"] = _canonical_payload_sha256(manifest)
    manifest_raw = _canonical_json(manifest)
    manifest_raw_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    sidecar_raw = (
        f"{manifest_raw_sha256}  {manifest_path.name}\n".encode("ascii")
    )

    for role, record in staged.items():
        if _sha(Path(record["source_path"])) != record["sha256"]:
            raise SessionLauncherSealError(f"{role} source changed before staging")
    for destination, raw in pending_writes:
        _write_new(destination, raw)
        validate_contained_regular_file(root, destination)
        if _sha(destination) != hashlib.sha256(raw).hexdigest():
            raise SessionLauncherSealError("staged public input copy changed")
    _write_new(manifest_path, manifest_raw)
    _write_new(sidecar_path, sidecar_raw)
    if (
        _sha(manifest_path) != manifest_raw_sha256
        or sidecar_path.read_bytes() != sidecar_raw
    ):
        raise SessionLauncherSealError("session manifest publication changed")

    build_receipt = {
        "schema_version": MANIFEST_BUILD_SCHEMA_VERSION,
        "status": "PASS",
        "stage": stage,
        "prepared_at_local": current.isoformat(),
        "production": reviewed_inventory["production"],
        "scope": manifest["scope"],
        "staged_public_inputs": dict(sorted(staged.items())),
        "discovery": {
            "sha256": discovery["sha256"],
            "semantic_sha256": discovery["semantic_sha256"],
            "expires_at_utc": discovery["expires_at_utc"],
            "unconstrained_discovery_only": True,
        },
        "session_manifest": {
            "path": str(manifest_path),
            "sha256": manifest_raw_sha256,
            "semantic_sha256": manifest["manifest_sha256"],
        },
        "session_manifest_sidecar": {
            "path": str(sidecar_path),
            "sha256": hashlib.sha256(sidecar_raw).hexdigest(),
        },
        "fixed_budget_pusd": int(FIXED_SESSION_BUDGET_PUSD),
        "fixed_max_session_seconds": FIXED_SESSION_SECONDS,
        "live_mutation_attempted": False,
        "credential_values_read_in_memory": False,
        "build_receipt_path": str(build_receipt_path),
    }
    _write_new(build_receipt_path, _canonical_json(build_receipt))
    return build_receipt


def _ps(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _replace(source: str, marker: str, value: str) -> str:
    quoted = f'"{marker}"'
    if source.count(quoted) != 1:
        raise SessionLauncherSealError(f"launcher marker is not unique: {marker}")
    return source.replace(quoted, _ps(value), 1)


def prepare_fixed_session_launcher(
    session_manifest_path: str | Path,
    expected_session_manifest_sha256: str,
    *,
    repo_root: str | Path = REPO_ROOT,
    template_path: str | Path = TEMPLATE_PATH,
    powershell_parser=_default_powershell_parser,
    attempt_root_validator=validate_private_attempt_root,
) -> dict:
    """Write the canonical no-argument launcher, review receipt, and sidecar."""

    manifest_path = validate_regular_nonreparse_file(session_manifest_path)
    root = validate_nonreparse_directory(repo_root)
    try:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SessionLauncherSealError("session manifest is unreadable") from exc
    observed_hash = hashlib.sha256(raw).hexdigest()
    if observed_hash != str(expected_session_manifest_sha256).lower():
        raise SessionLauncherSealError("reviewed session manifest hash changed")
    sidecar = manifest_path.with_suffix(manifest_path.suffix + ".sha256")
    validate_regular_nonreparse_file(sidecar)
    if sidecar.read_text(encoding="ascii") != f"{observed_hash}  {manifest_path.name}\n":
        raise SessionLauncherSealError("session manifest sidecar changed")
    if manifest.get("schema_version") != SESSION_SCHEMA_VERSION:
        raise SessionLauncherSealError("session manifest schema is unsupported")
    stage = str(manifest.get("stage") or "")
    scope = manifest.get("scope") or {}
    raw_attempt_root = Path(str(scope.get("attempt_root") or ""))
    if attempt_root_validator(raw_attempt_root).get("status") != "PASS":
        raise SessionLauncherSealError("attempt root security validation did not pass")
    attempt_root = validate_nonreparse_directory(raw_attempt_root)
    if manifest_path != (
        attempt_root / "inputs" / f"{stage}-session-manifest.json"
    ).resolve():
        raise SessionLauncherSealError("session manifest path is not canonical")
    production = manifest.get("production") or {}
    if Path(str(production.get("root") or "")).resolve() != root:
        raise SessionLauncherSealError("launcher repository differs from reviewed production")
    python = validate_regular_nonreparse_file(str(production.get("python") or ""))
    if python != (root / "venv/Scripts/python.exe").resolve() or not python.is_file():
        raise SessionLauncherSealError("reviewed production interpreter is unavailable")
    expected_python_sha256 = str(
        manifest.get("production_python_sha256") or ""
    ).lower()
    if expected_python_sha256 != _sha(python):
        raise SessionLauncherSealError("reviewed production interpreter hash changed")
    bootstrap_hashes = manifest.get("session_bootstrap_sha256")
    if not isinstance(bootstrap_hashes, dict) or set(bootstrap_hashes) != set(
        SESSION_BOOTSTRAP_PATHS
    ):
        raise SessionLauncherSealError("session bootstrap closure is incomplete")
    for relative, expected_hash in bootstrap_hashes.items():
        source = validate_regular_nonreparse_file(root / relative)
        if _sha(source) != str(expected_hash).lower():
            raise SessionLauncherSealError("session bootstrap source hash changed")
    candidate = attempt_root / "incoming" / f"fresh-{stage}-candidate.json"
    if candidate.exists():
        raise SessionLauncherSealError("fixed candidate inbox must be new at review time")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    launcher = attempt_root / "session" / f"{stage}-launch.ps1"
    receipt_path = attempt_root / "session" / f"{stage}-launcher-review.json"
    receipt_sidecar = receipt_path.with_suffix(receipt_path.suffix + ".sha256")
    if any(path.exists() for path in (launcher, receipt_path, receipt_sidecar)):
        raise SessionLauncherSealError("fixed session launcher namespace is spent")
    template = validate_regular_nonreparse_file(template_path)
    runner_source = root / RUNNER_SOURCE.relative_to(REPO_ROOT)
    validate_regular_nonreparse_file(runner_source)
    rendered = template.read_text(encoding="utf-8")
    replacements = {
        "__SESSION_REPO_ROOT__": str(root),
        "__SESSION_PYTHON__": str(python),
        "__SESSION_PYTHON_SHA256__": expected_python_sha256,
        "__SESSION_RUNNER_SOURCE__": str(runner_source),
        "__SESSION_RUNNER_SHA256__": _sha(runner_source),
        "__SESSION_MANIFEST__": str(manifest_path),
        "__SESSION_MANIFEST_SHA256__": observed_hash,
        "__SESSION_MANIFEST_SIDECAR__": str(sidecar),
        "__SESSION_MANIFEST_SIDECAR_SHA256__": _sha(sidecar),
        "__SESSION_CANDIDATE_INBOX__": str(candidate.resolve()),
    }
    for marker, value in replacements.items():
        rendered = _replace(rendered, marker, value)
    powershell_parser(rendered)
    launcher_raw = rendered.encode("utf-8-sig")
    receipt = {
        "schema_version": "international_live_session_launcher_review_v0.1",
        "status": "PASS",
        "stage": stage,
        "session_manifest": {
            "path": str(manifest_path),
            "sha256": observed_hash,
            "sidecar_path": str(sidecar),
            "sidecar_sha256": _sha(sidecar),
        },
        "candidate_inbox": str(candidate.resolve()),
        "launcher": {
            "path": str(launcher.resolve()),
            "sha256": hashlib.sha256(launcher_raw).hexdigest(),
            "bytes": len(launcher_raw),
        },
        "runner_source": {"path": str(runner_source), "sha256": _sha(runner_source)},
        "launcher_template": {"path": str(template), "sha256": _sha(template)},
        "production_python": {
            "path": str(python),
            "sha256": expected_python_sha256,
        },
        "session_bootstrap_sha256": dict(sorted(bootstrap_hashes.items())),
        "no_argument_surface": True,
        "live_mutation_attempted": False,
        "credential_values_read_in_memory": False,
    }
    receipt_raw = _canonical_json(receipt)
    _write_new(launcher, launcher_raw)
    _write_new(receipt_path, receipt_raw)
    _write_new(
        receipt_sidecar,
        f"{hashlib.sha256(receipt_raw).hexdigest()}  {receipt_path.name}\n".encode(
            "ascii"
        ),
    )
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    initializer = subparsers.add_parser(
        "init-attempt",
        help="create one external private fixed-session attempt namespace",
    )
    initializer.add_argument("--attempt-root", required=True)
    manifest = subparsers.add_parser(
        "prepare-manifest",
        help="stage reviewed public inputs and publish one fixed session manifest",
    )
    manifest.add_argument("--stage", choices=fixed_sealer.STAGES, required=True)
    manifest.add_argument("--discovery-plan", required=True)
    manifest.add_argument("--identity-source", required=True)
    manifest.add_argument("--credential-import-receipt-source", required=True)
    manifest.add_argument("--credential-reference-manifest-source", required=True)
    manifest.add_argument("--attempt-root", required=True)
    manifest.add_argument("--lease-workload", required=True)
    manifest.add_argument("--reviewed-status-flags-json")
    launcher = subparsers.add_parser(
        "prepare-launcher",
        help="publish a no-argument launcher for one independently reviewed manifest",
    )
    launcher.add_argument("--session-manifest", required=True)
    launcher.add_argument("--expected-session-manifest-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if raw_args and "--session-manifest" in raw_args and raw_args[0].startswith("-"):
        # Preserve the original public launcher-preparation invocation.
        raw_args.insert(0, "prepare-launcher")
    args = build_parser().parse_args(raw_args)
    try:
        if args.command == "init-attempt":
            result = initialize_private_attempt_root(args.attempt_root)
        elif args.command == "prepare-manifest":
            result = prepare_fixed_session_manifest(
                stage=args.stage,
                discovery_plan_path=args.discovery_plan,
                identity_source_path=args.identity_source,
                credential_import_receipt_source_path=(
                    args.credential_import_receipt_source
                ),
                credential_reference_manifest_source_path=(
                    args.credential_reference_manifest_source
                ),
                attempt_root=args.attempt_root,
                lease_workload=args.lease_workload,
                reviewed_status_flags_path=args.reviewed_status_flags_json,
            )
        else:
            result = prepare_fixed_session_launcher(
                args.session_manifest,
                args.expected_session_manifest_sha256,
            )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "BLOCK",
                    "operation": args.command,
                    "exception_type": type(exc).__name__,
                    "live_mutation_attempted": False,
                    "credential_values_read_in_memory": False,
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
