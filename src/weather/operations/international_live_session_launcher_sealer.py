"""Prepare private fixed-session manifests and reviewed no-argument launchers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from weather.market.mm_live_candidate_cli import (
    load_candidate_discovery_gate,
    validate_bound_economics_acceptance_files,
)
from weather.market.market_registry import REGISTRY as MARKET_REGISTRY
from weather.execution_host import (
    current_execution_principal_id,
    require_current_capture_execution_assignment,
    require_current_portable_execution_assignment,
)
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
    CAPTURE_COLOCATED_HOST_PROFILE,
    EXECUTION_HOST_PROFILES,
    PORTABLE_EXECUTION_HOST_PROFILE,
    assert_no_ambient_market_registry_override,
    canonical_windows_powershell,
    current_execution_host_id,
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
LAUNCHER_REVIEW_SCHEMA_VERSION = schema_version(
    "international_live_session_launcher_review"
)
FIXED_SESSION_BUDGET_PUSD = Decimal("10")
FIXED_SESSION_SECONDS_BY_PROFILE = {
    CAPTURE_COLOCATED_HOST_PROFILE: 120,
    PORTABLE_EXECUTION_HOST_PROFILE: MAX_SESSION_SECONDS,
}
ATTEMPT_DIRECTORIES = ("inputs", "incoming", "session")
STAGED_INPUT_LAYOUTS = {
    "stage0": {
        "identity": fixed_sealer.INPUT_LAYOUTS["stage0"]["identity"],
        "credential_import_receipt": (
            "inputs/stage0-credential-import-receipt.json"
        ),
        "credential_reference_manifest": (
            "inputs/stage0-credential-reference-manifest.json"
        ),
        "accepted_economics_snapshot": fixed_sealer.INPUT_LAYOUTS["stage0"][
            "accepted_economics_snapshot"
        ],
        "economics_drift_report": fixed_sealer.INPUT_LAYOUTS["stage0"][
            "economics_drift_report"
        ],
        "discovery_plan": "inputs/stage0-discovery-plan.json",
        "reviewed_status_flags": "inputs/stage0-reviewed-status-flags.json",
        "build_receipt": "inputs/stage0-session-manifest-build-receipt.json",
    },
    "stage1_cancel_all": {
        "identity": fixed_sealer.INPUT_LAYOUTS["stage1_cancel_all"]["identity"],
        "credential_import_receipt": (
            "inputs/stage1-cancel-all-credential-import-receipt.json"
        ),
        "credential_reference_manifest": (
            "inputs/stage1-cancel-all-credential-reference-manifest.json"
        ),
        "accepted_economics_snapshot": fixed_sealer.INPUT_LAYOUTS[
            "stage1_cancel_all"
        ]["accepted_economics_snapshot"],
        "economics_drift_report": fixed_sealer.INPUT_LAYOUTS[
            "stage1_cancel_all"
        ]["economics_drift_report"],
        "discovery_plan": "inputs/stage1-cancel-all-discovery-plan.json",
        "reviewed_status_flags": (
            "inputs/stage1-cancel-all-reviewed-status-flags.json"
        ),
        "build_receipt": (
            "inputs/stage1-cancel-all-session-manifest-build-receipt.json"
        ),
    },
    "stage1_dead_man": {
        "identity": fixed_sealer.INPUT_LAYOUTS["stage1_dead_man"]["identity"],
        "credential_import_receipt": (
            "inputs/stage1-dead-man-credential-import-receipt.json"
        ),
        "credential_reference_manifest": (
            "inputs/stage1-dead-man-credential-reference-manifest.json"
        ),
        "accepted_economics_snapshot": fixed_sealer.INPUT_LAYOUTS[
            "stage1_dead_man"
        ]["accepted_economics_snapshot"],
        "economics_drift_report": fixed_sealer.INPUT_LAYOUTS[
            "stage1_dead_man"
        ]["economics_drift_report"],
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


def _canonical_lease_workload(attempt_root: Path, stage: str) -> str:
    root_text = os.path.normcase(str(attempt_root.resolve()))
    root_hash = hashlib.sha256(root_text.encode("utf-8")).hexdigest()[:12]
    workload = f"InternationalLive-{stage}-{attempt_root.name}-{root_hash}"
    if fixed_sealer.WORKLOAD_RE.fullmatch(workload) is None:
        raise SessionLauncherSealError(
            "attempt basename cannot form a canonical lease workload"
        )
    return workload


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
  $rule=[Security.AccessControl.FileSystemAccessRule]::new(
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
        "lease_workloads": {
            stage: _canonical_lease_workload(root, stage)
            for stage in fixed_sealer.STAGES
        },
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
            "local_master",
            "cached_origin_master",
            "remote_master",
            "remote_master_ref",
            "live_remote_master_equal",
            "tree",
            "object_format",
            "python",
            "python_sha256",
            "git_executable",
            "git_executable_sha256",
            "canonical_origin_url",
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
    git_executable = validate_regular_nonreparse_file(
        str(production["git_executable"])
    )
    git_hash = _require_sha256(
        production["git_executable_sha256"], label="Git executable hash"
    )
    if not all(
        (
            _same_path(root, production_root),
            production["branch"] == "master",
            production["local_master"] == commit,
            production["cached_origin_master"] == commit,
            production["remote_master"] == commit,
            production["remote_master_ref"] == fixed_sealer.REMOTE_MASTER_REF,
            production["live_remote_master_equal"] is True,
            production["interrupt_cleanup_ancestor_integrated"] is True,
            oid_length is not None,
            fixed_sealer.GIT_OID_RE.fullmatch(commit) is not None,
            fixed_sealer.GIT_OID_RE.fullmatch(tree) is not None,
            len(commit) == oid_length,
            len(tree) == oid_length,
            _same_path(python, expected_python),
            _sha(python) == python_hash,
            _same_path(git_executable, fixed_sealer.canonical_git_executable()),
            _sha(git_executable) == git_hash,
            production["canonical_origin_url"]
            == fixed_sealer.CANONICAL_ORIGIN_URL,
        )
    ):
        raise SessionLauncherSealError("public inventory production is not canonical")
    production_record = {
        "root": str(root),
        "branch": "master",
        "commit": commit,
        "tree": tree,
        "python": str(python),
        "git_executable": str(git_executable),
        "git_executable_sha256": git_hash,
        "canonical_origin_url": fixed_sealer.CANONICAL_ORIGIN_URL,
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


def _assert_unique_workload(attempt_root: Path, stage: str, workload: str) -> None:
    if workload != _canonical_lease_workload(attempt_root, stage):
        raise SessionLauncherSealError(
            "lease workload is not the canonical unique attempt workload"
        )
    for existing_stage in fixed_sealer.STAGES:
        manifest_path = (
            attempt_root / "inputs" / f"{existing_stage}-session-manifest.json"
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
    accepted_economics_snapshot_source_path: str | Path,
    economics_drift_report_source_path: str | Path,
    attempt_root: str | Path,
    lease_workload: str,
    execution_host_profile: str,
    reviewed_status_flags_path: str | Path | None = None,
    production_root: str | Path = REPO_ROOT,
    now: datetime | None = None,
    inventory_builder=fixed_sealer.build_public_inventory,
    git_state_validator: Callable[[Mapping[str, Any]], Any] | None = None,
    attempt_root_validator=validate_private_attempt_root,
    execution_host_id_provider: Callable[[], str] = current_execution_host_id,
    capture_assignment_validator=require_current_capture_execution_assignment,
    portable_assignment_validator=require_current_portable_execution_assignment,
) -> dict[str, Any]:
    """Build one fixed-session manifest from current public, reviewed inputs."""

    assert_no_ambient_market_registry_override()
    if stage not in fixed_sealer.STAGES:
        raise SessionLauncherSealError("session manifest stage is unsupported")
    if execution_host_profile not in EXECUTION_HOST_PROFILES:
        raise SessionLauncherSealError("execution host profile is unsupported")
    fixed_session_seconds = FIXED_SESSION_SECONDS_BY_PROFILE[
        execution_host_profile
    ]
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
    _assert_unique_workload(root, stage, str(lease_workload))
    execution_host_id = str(execution_host_id_provider()).lower()
    if fixed_sealer.SHA256_RE.fullmatch(execution_host_id) is None:
        raise SessionLauncherSealError("execution host identity is invalid")
    if execution_host_profile == PORTABLE_EXECUTION_HOST_PROFILE:
        try:
            portable_assignment_validator(
                production / fixed_sealer.EXECUTION_HOST_ASSIGNMENT_PATH,
                execution_host_id=execution_host_id,
                execution_principal_id=current_execution_principal_id(),
            )
        except Exception as exc:
            raise SessionLauncherSealError(
                "current host/principal is not the active portable executor"
            ) from exc
    else:
        try:
            capture_assignment_validator(
                production / fixed_sealer.EXECUTION_HOST_ASSIGNMENT_PATH,
                execution_host_id=execution_host_id,
            )
        except Exception as exc:
            raise SessionLauncherSealError(
                "current host is not eligible for capture-colocated execution"
            ) from exc

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
        "accepted_economics_snapshot": accepted_economics_snapshot_source_path,
        "economics_drift_report": economics_drift_report_source_path,
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

    try:
        discovery = load_candidate_discovery_gate(
            Path(staged["discovery_plan"]["source_path"]),
            now=current,
        )
    except RuntimeError as exc:
        raise SessionLauncherSealError(
            f"discovery plan failed complete candidate gate: {exc}"
        ) from exc
    if discovery["plan_sha256"] != staged["discovery_plan"]["sha256"]:
        raise SessionLauncherSealError("discovery plan changed during validation")
    market = MARKET_REGISTRY.get(str(discovery.get("market_id") or ""))
    if market is None:
        raise SessionLauncherSealError("discovery plan market is not built in")
    try:
        validate_bound_economics_acceptance_files(
            Path(staged["accepted_economics_snapshot"]["source_path"]),
            Path(staged["economics_drift_report"]["source_path"]),
            discovery["economics_acceptance"],
            target_date=discovery["target_date"],
            current_snapshot_id=discovery["economics_acceptance"][
                "accepted_snapshot_id"
            ],
            current_snapshot_sha256=discovery["economics_acceptance"][
                "accepted_snapshot_sha256"
            ],
        )
    except RuntimeError as exc:
        raise SessionLauncherSealError(
            "discovery plan economics acceptance does not match its source evidence"
        ) from exc
    reference_payload = fixed_sealer._validate_credential_reference_manifest(
        Path(staged["credential_reference_manifest"]["source_path"])
    )
    try:
        fixed_sealer._validate_credential_import_receipt(
            Path(staged["credential_import_receipt"]["source_path"]),
            required_mode=fixed_sealer.FIRST_SESSION_CREDENTIAL_MODE,
            now=current,
        )
    except fixed_sealer.SealError as exc:
        raise SessionLauncherSealError(
            "first-session manifest requires compare-only credential evidence"
        ) from exc
    fixed_sealer._validate_identity(
        Path(staged["identity"]["source_path"]),
        requested_budget=FIXED_SESSION_BUDGET_PUSD,
        expected_reference=reference_payload,
    )

    reviewed_status_flags: list[dict[str, str]] = []
    if (
        execution_host_profile == PORTABLE_EXECUTION_HOST_PROFILE
        and reviewed_status_flags_path is not None
    ):
        raise SessionLauncherSealError(
            "portable execution hosts do not consume capture-host status exceptions"
        )
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
            "execution_host_profile": execution_host_profile,
            "execution_host_id": execution_host_id,
            "market_id": market.id,
            "market_timezone": market.timezone,
            "max_session_seconds": fixed_session_seconds,
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
                "accepted_economics_snapshot",
                "economics_drift_report",
            )
        },
        "economics_acceptance": discovery["economics_acceptance"],
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

    final_inventory = _validate_public_inventory(
        stage,
        production,
        inventory,
        git_state_validator=git_state_validator,
    )
    if final_inventory != reviewed_inventory:
        raise SessionLauncherSealError("public inventory changed before publication")
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
            "sha256": discovery["plan_sha256"],
            "semantic_sha256": discovery["semantic_plan_sha256"],
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
        "fixed_max_session_seconds": fixed_session_seconds,
        "live_mutation_attempted": False,
        "credential_values_read_in_memory": False,
        "build_receipt_path": str(build_receipt_path),
    }
    _write_new(build_receipt_path, _canonical_json(build_receipt))
    return build_receipt


def _validate_manifest_build_receipt(
    *,
    stage: str,
    attempt_root: Path,
    production_root: Path,
    manifest_path: Path,
    manifest: Mapping[str, Any],
    manifest_raw_sha256: str,
    sidecar_path: Path,
    expected_receipt_sha256: str,
    now: datetime,
) -> dict[str, str]:
    """Validate the canonical builder receipt and every public staged binding."""

    layout = STAGED_INPUT_LAYOUTS[stage]
    expected_path = (attempt_root / layout["build_receipt"]).resolve()
    try:
        receipt_path = validate_contained_regular_file(attempt_root, expected_path)
    except Exception as exc:
        raise SessionLauncherSealError(
            "canonical session manifest build receipt is absent or redirected"
        ) from exc
    expected_hash = _require_sha256(
        expected_receipt_sha256,
        label="reviewed session manifest build receipt hash",
    )
    observed_hash = _sha(receipt_path)
    if observed_hash != expected_hash:
        raise SessionLauncherSealError(
            "reviewed session manifest build receipt hash changed"
        )
    receipt, receipt_raw = _read_json_object(
        receipt_path,
        label="session manifest build receipt",
    )
    if receipt_raw != _canonical_json(receipt):
        raise SessionLauncherSealError(
            "session manifest build receipt bytes are not canonical"
        )
    _require_exact_object(
        receipt,
        {
            "schema_version", "status", "stage", "prepared_at_local",
            "production", "scope", "staged_public_inputs", "discovery",
            "session_manifest", "session_manifest_sidecar", "fixed_budget_pusd",
            "fixed_max_session_seconds", "live_mutation_attempted",
            "credential_values_read_in_memory", "build_receipt_path",
        },
        label="session manifest build receipt",
    )
    prepared = _parse_aware_utc(
        receipt["prepared_at_local"],
        label="session manifest build receipt preparation",
    )
    manifest_record = _require_exact_object(
        receipt["session_manifest"],
        {"path", "sha256", "semantic_sha256"},
        label="session manifest build receipt manifest",
    )
    sidecar_record = _require_exact_object(
        receipt["session_manifest_sidecar"],
        {"path", "sha256"},
        label="session manifest build receipt sidecar",
    )
    discovery_record = _require_exact_object(
        receipt["discovery"],
        {"sha256", "semantic_sha256", "expires_at_utc", "unconstrained_discovery_only"},
        label="session manifest build receipt discovery",
    )
    _require_exact_object(
        manifest,
        {
            "schema_version", "manifest_sha256", "stage", "production", "scope",
            "inputs", "economics_acceptance", "reviewed_status_flags",
            "template_sha256", "source_sha256",
            "production_python_sha256", "session_bootstrap_sha256",
        },
        label="session manifest",
    )
    production = _require_exact_object(
        manifest["production"],
        {
            "root", "branch", "commit", "tree", "python",
            "git_executable", "git_executable_sha256", "canonical_origin_url",
        },
        label="session manifest production",
    )
    scope = _require_exact_object(
        manifest["scope"],
        {
            "target_date", "condition_id", "token_id", "requested_budget_pusd",
            "attempt_root", "lease_workload", "execution_host_profile",
            "execution_host_id", "market_id", "market_timezone",
            "max_session_seconds",
        },
        label="session manifest scope",
    )
    inputs = _require_exact_object(
        manifest["inputs"],
        {
            "identity", "credential_import_receipt",
            "credential_reference_manifest", "accepted_economics_snapshot",
            "economics_drift_report",
        },
        label="session manifest inputs",
    )
    expected_session_seconds = FIXED_SESSION_SECONDS_BY_PROFILE.get(
        str(scope["execution_host_profile"])
    )
    if not all(
        (
            receipt["schema_version"] == MANIFEST_BUILD_SCHEMA_VERSION,
            receipt["status"] == "PASS",
            receipt["stage"] == stage,
            receipt["production"] == production,
            receipt["scope"] == scope,
            type(receipt["fixed_budget_pusd"]) is int,
            receipt["fixed_budget_pusd"] == int(FIXED_SESSION_BUDGET_PUSD),
            type(receipt["fixed_max_session_seconds"]) is int,
            receipt["fixed_max_session_seconds"] == expected_session_seconds,
            receipt["live_mutation_attempted"] is False,
            receipt["credential_values_read_in_memory"] is False,
            Path(str(receipt["build_receipt_path"])).resolve() == receipt_path,
            manifest["schema_version"] == SESSION_SCHEMA_VERSION,
            manifest["stage"] == stage,
            manifest["manifest_sha256"] == _canonical_payload_sha256(manifest),
            manifest_path.read_bytes() == _canonical_json(manifest),
            Path(str(production["root"])).resolve() == production_root,
            production["branch"] == "master",
            Path(str(scope["attempt_root"])).resolve() == attempt_root,
            scope["lease_workload"] == _canonical_lease_workload(attempt_root, stage),
            scope["execution_host_profile"] in EXECUTION_HOST_PROFILES,
            scope["execution_host_id"] == current_execution_host_id(),
            fixed_sealer.SHA256_RE.fullmatch(
                str(scope["execution_host_id"] or "").lower()
            )
            is not None,
            str(scope["market_id"] or "") in MARKET_REGISTRY,
            (
                str(scope["market_timezone"] or "")
                == MARKET_REGISTRY[str(scope["market_id"])].timezone
                if str(scope["market_id"] or "") in MARKET_REGISTRY
                else False
            ),
            (
                scope["execution_host_profile"]
                != PORTABLE_EXECUTION_HOST_PROFILE
                or manifest["reviewed_status_flags"] == []
            ),
            type(scope["requested_budget_pusd"]) is int,
            scope["requested_budget_pusd"] == int(FIXED_SESSION_BUDGET_PUSD),
            type(scope["max_session_seconds"]) is int,
            scope["max_session_seconds"] == expected_session_seconds,
            manifest_record["path"] == str(manifest_path),
            manifest_record["sha256"] == manifest_raw_sha256,
            manifest_record["semantic_sha256"] == manifest["manifest_sha256"],
            sidecar_record["path"] == str(sidecar_path),
            sidecar_record["sha256"] == _sha(sidecar_path),
        )
    ):
        raise SessionLauncherSealError(
            "session manifest build receipt does not exactly bind the manifest"
        )

    staged_value = receipt["staged_public_inputs"]
    if not isinstance(staged_value, dict):
        raise SessionLauncherSealError("staged public inputs are not an object")
    required_roles = {
        "identity", "credential_import_receipt",
        "credential_reference_manifest", "accepted_economics_snapshot",
        "economics_drift_report", "discovery_plan",
    }
    if not required_roles.issubset(staged_value) or not set(staged_value).issubset(
        required_roles | {"reviewed_status_flags"}
    ):
        raise SessionLauncherSealError("staged public input roles are not exact")
    staged: dict[str, Mapping[str, Any]] = {}
    for role, value in staged_value.items():
        record = _require_exact_object(
            value,
            {"source_path", "path", "sha256", "bytes"},
            label=f"staged public input {role}",
        )
        expected_staged_path = (attempt_root / layout[role]).resolve()
        staged_path = validate_contained_regular_file(attempt_root, expected_staged_path)
        digest = _require_sha256(record["sha256"], label=f"staged public input {role} hash")
        source_path = Path(str(record["source_path"]))
        if not all(
            (
                Path(str(record["path"])).resolve() == staged_path,
                source_path.is_absolute(),
                not _same_path(source_path, staged_path),
                not _same_path(source_path, production_root),
                not _is_within(production_root, source_path),
                _sha(staged_path) == digest,
                isinstance(record["bytes"], int),
                not isinstance(record["bytes"], bool),
                record["bytes"] == staged_path.stat().st_size,
            )
        ):
            raise SessionLauncherSealError(f"staged public input {role} changed")
        staged[role] = record

    for role in (
        "identity", "credential_import_receipt", "credential_reference_manifest",
        "accepted_economics_snapshot", "economics_drift_report",
    ):
        manifest_input = _require_exact_object(
            inputs[role],
            {"path", "sha256"},
            label=f"session manifest input {role}",
        )
        if manifest_input != {
            "path": staged[role]["path"],
            "sha256": staged[role]["sha256"],
        }:
            raise SessionLauncherSealError(
                f"session manifest input {role} differs from its staged receipt"
            )

    try:
        fixed_sealer._validate_credential_import_receipt(
            Path(str(staged["credential_import_receipt"]["path"])),
            required_mode=fixed_sealer.FIRST_SESSION_CREDENTIAL_MODE,
            now=now,
        )
    except fixed_sealer.SealError as exc:
        raise SessionLauncherSealError(
            "staged first-session credential evidence is not compare-only"
        ) from exc

    discovery_path = Path(str(staged["discovery_plan"]["path"]))
    try:
        discovery = load_candidate_discovery_gate(discovery_path, now=prepared)
    except RuntimeError as exc:
        raise SessionLauncherSealError(
            "staged discovery does not satisfy the canonical builder receipt"
        ) from exc
    if not all(
        (
            discovery_record["sha256"] == discovery["plan_sha256"]
            == staged["discovery_plan"]["sha256"],
            discovery_record["semantic_sha256"]
            == discovery["semantic_plan_sha256"],
            discovery_record["expires_at_utc"] == discovery["expires_at_utc"],
            discovery_record["unconstrained_discovery_only"] is True,
            scope["target_date"] == discovery["target_date"],
            scope["market_id"] == discovery["market_id"],
            scope["condition_id"] == discovery["condition_id"],
            scope["token_id"] == discovery["token_id"],
            manifest["economics_acceptance"]
            == discovery["economics_acceptance"],
        )
    ):
        raise SessionLauncherSealError(
            "session manifest scope differs from its staged discovery"
        )
    try:
        validate_bound_economics_acceptance_files(
            Path(str(staged["accepted_economics_snapshot"]["path"])),
            Path(str(staged["economics_drift_report"]["path"])),
            manifest["economics_acceptance"],
            target_date=scope["target_date"],
            current_snapshot_id=discovery["economics_acceptance"][
                "accepted_snapshot_id"
            ],
            current_snapshot_sha256=discovery["economics_acceptance"][
                "accepted_snapshot_sha256"
            ],
        )
    except RuntimeError as exc:
        raise SessionLauncherSealError(
            "staged economics acceptance evidence differs from the manifest"
        ) from exc

    status_flags = manifest["reviewed_status_flags"]
    if not isinstance(status_flags, list):
        raise SessionLauncherSealError("session reviewed status flags are not a list")
    if "reviewed_status_flags" in staged:
        if _load_reviewed_status_flags(
            Path(str(staged["reviewed_status_flags"]["path"]))
        ) != status_flags:
            raise SessionLauncherSealError("reviewed status flags changed after staging")
    elif status_flags:
        raise SessionLauncherSealError("reviewed status flags have no staged source")
    return {"path": str(receipt_path), "sha256": observed_hash}


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
    expected_manifest_build_receipt_sha256: str,
    *,
    repo_root: str | Path = REPO_ROOT,
    template_path: str | Path = TEMPLATE_PATH,
    powershell_parser=_default_powershell_parser,
    attempt_root_validator=validate_private_attempt_root,
    capture_assignment_validator=require_current_capture_execution_assignment,
    portable_assignment_validator=require_current_portable_execution_assignment,
    now: datetime | None = None,
) -> dict:
    """Write the canonical no-argument launcher, review receipt, and sidecar."""

    assert_no_ambient_market_registry_override()
    current = now or datetime.now().astimezone()
    if current.tzinfo is None or current.utcoffset() is None:
        raise SessionLauncherSealError("launcher review clock is not timezone-aware")
    manifest_path = validate_regular_nonreparse_file(session_manifest_path)
    root = validate_nonreparse_directory(repo_root)
    try:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SessionLauncherSealError("session manifest is unreadable") from exc
    observed_hash = hashlib.sha256(raw).hexdigest()
    if not isinstance(manifest, dict):
        raise SessionLauncherSealError("session manifest is not a JSON object")
    if observed_hash != str(expected_session_manifest_sha256).lower():
        raise SessionLauncherSealError("reviewed session manifest hash changed")
    sidecar = manifest_path.with_suffix(manifest_path.suffix + ".sha256")
    validate_regular_nonreparse_file(sidecar)
    if sidecar.read_text(encoding="ascii") != f"{observed_hash}  {manifest_path.name}\n":
        raise SessionLauncherSealError("session manifest sidecar changed")
    if manifest.get("schema_version") != SESSION_SCHEMA_VERSION:
        raise SessionLauncherSealError("session manifest schema is unsupported")
    stage = str(manifest.get("stage") or "")
    if stage not in fixed_sealer.STAGES:
        raise SessionLauncherSealError("session manifest stage is unsupported")
    scope = manifest.get("scope") or {}
    execution_host_profile = str(scope.get("execution_host_profile") or "")
    execution_host_id = str(scope.get("execution_host_id") or "").lower()
    try:
        if execution_host_profile == PORTABLE_EXECUTION_HOST_PROFILE:
            portable_assignment_validator(
                root / fixed_sealer.EXECUTION_HOST_ASSIGNMENT_PATH,
                execution_host_id=execution_host_id,
                execution_principal_id=current_execution_principal_id(),
            )
        elif execution_host_profile == CAPTURE_COLOCATED_HOST_PROFILE:
            capture_assignment_validator(
                root / fixed_sealer.EXECUTION_HOST_ASSIGNMENT_PATH,
                execution_host_id=execution_host_id,
            )
        else:
            raise RuntimeError("unsupported execution host profile")
    except Exception as exc:
        raise SessionLauncherSealError(
            "current host no longer matches the reviewed execution profile"
        ) from exc
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
    build_receipt = _validate_manifest_build_receipt(
        stage=stage,
        attempt_root=attempt_root,
        production_root=root,
        manifest_path=manifest_path,
        manifest=manifest,
        manifest_raw_sha256=observed_hash,
        sidecar_path=sidecar,
        expected_receipt_sha256=expected_manifest_build_receipt_sha256,
        now=current,
    )
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
    source_hashes = manifest.get("source_sha256")
    if not isinstance(source_hashes, dict):
        raise SessionLauncherSealError("session source closure is unavailable")
    expected_job_helper_sha256 = str(
        source_hashes.get(fixed_sealer.WINDOWS_JOB_HELPER_PATH) or ""
    ).lower()
    job_helper = validate_regular_nonreparse_file(
        root / fixed_sealer.WINDOWS_JOB_HELPER_PATH
    )
    if (
        fixed_sealer.SHA256_RE.fullmatch(expected_job_helper_sha256) is None
        or _sha(job_helper) != expected_job_helper_sha256
    ):
        raise SessionLauncherSealError("session Windows Job helper hash changed")
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
        "__SESSION_MANIFEST_BUILD_RECEIPT__": build_receipt["path"],
        "__SESSION_MANIFEST_BUILD_RECEIPT_SHA256__": build_receipt["sha256"],
        "__SESSION_CANDIDATE_INBOX__": str(candidate.resolve()),
        "__SESSION_WINDOWS_JOB_HELPER_SHA256__": expected_job_helper_sha256,
    }
    for marker, value in replacements.items():
        rendered = _replace(rendered, marker, value)
    powershell_parser(rendered)
    launcher_raw = rendered.encode("utf-8-sig")
    receipt = {
        "schema_version": LAUNCHER_REVIEW_SCHEMA_VERSION,
        "status": "PASS",
        "stage": stage,
        "session_manifest": {
            "path": str(manifest_path),
            "sha256": observed_hash,
            "semantic_sha256": manifest["manifest_sha256"],
            "sidecar_path": str(sidecar),
            "sidecar_sha256": _sha(sidecar),
        },
        "manifest_build_receipt": build_receipt,
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
    manifest.add_argument(
        "--credential-import-receipt-source",
        required=True,
        help=(
            "fresh host-and-principal-bound v0.4 compare-only receipt proving all four "
            "existing fixed entries with zero credential-store mutation"
        ),
    )
    manifest.add_argument("--credential-reference-manifest-source", required=True)
    manifest.add_argument("--accepted-economics-snapshot-source", required=True)
    manifest.add_argument("--economics-drift-report-source", required=True)
    manifest.add_argument("--attempt-root", required=True)
    manifest.add_argument("--lease-workload", required=True)
    manifest.add_argument(
        "--execution-host-profile",
        choices=sorted(EXECUTION_HOST_PROFILES),
        required=True,
        help=(
            "capture_colocated_v1 retains production capture/tape and quiet-window "
            "checks; portable_execution_v1 binds an execution-only PC"
        ),
    )
    manifest.add_argument("--reviewed-status-flags-json")
    launcher = subparsers.add_parser(
        "prepare-launcher",
        help="publish a no-argument launcher for one independently reviewed manifest",
    )
    launcher.add_argument("--session-manifest", required=True)
    launcher.add_argument("--expected-session-manifest-sha256", required=True)
    launcher.add_argument(
        "--expected-manifest-build-receipt-sha256",
        required=True,
    )
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
                accepted_economics_snapshot_source_path=(
                    args.accepted_economics_snapshot_source
                ),
                economics_drift_report_source_path=(
                    args.economics_drift_report_source
                ),
                attempt_root=args.attempt_root,
                lease_workload=args.lease_workload,
                execution_host_profile=args.execution_host_profile,
                reviewed_status_flags_path=args.reviewed_status_flags_json,
            )
        else:
            result = prepare_fixed_session_launcher(
                args.session_manifest,
                args.expected_session_manifest_sha256,
                args.expected_manifest_build_receipt_sha256,
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
