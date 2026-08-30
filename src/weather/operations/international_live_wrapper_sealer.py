"""Deterministically seal fixed-scope International wrappers without executing."""

from __future__ import annotations
import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from weather.paths import REPO_ROOT
from weather.market.mm_geographic_eligibility import (
    GeographicEligibilityError,
    validate_geographic_eligibility_receipt,
)
from weather.market.mm_live_candidate_cli import (
    ECONOMICS_ACCEPTANCE_KEYS,
    MAX_PAPER_QUOTE_TTL_SECONDS,
    SCHEMA_VERSION as CANDIDATE_SCHEMA_VERSION,
    economics_acceptance_acknowledgment,
    load_stage1_candidate_gate,
    validate_bound_economics_acceptance_files,
    validate_candidate_substrate_binding,
)
from weather.market.mm_live_lifecycle_probe import (
    verify_stage1_user_stream_journal,
)
from weather.market.market_registry import REGISTRY as MARKET_REGISTRY
from weather.operations import international_live_time_window as live_time_window
from weather.operations.international_live_lineage import (
    CREDENTIAL_TOPOLOGY_KEYS,
    EXPECTED_CREDENTIAL_IMPORT_CHECKS,
    EXPECTED_CREDENTIAL_REFERENCES,
    exact_run_lineage,
)
from weather.operations.live_path_security import (
    CAPTURE_COLOCATED_HOST_PROFILE,
    EXECUTION_HOST_PROFILES,
    PORTABLE_EXECUTION_HOST_PROFILE,
    SESSION_BOOTSTRAP_PATHS,
    STATUS_ATTESTATION_SOURCE_PATHS,
    NETWORK_REDIRECT_ENVIRONMENT_KEYS,
    MARKET_REGISTRY_OVERRIDE_ENVIRONMENT_KEY,
    assert_no_ambient_market_registry_override,
    assert_no_ambient_proxy_configuration,
    canonical_git_executable,
    canonical_windows_powershell,
    current_execution_host_id,
    repository_python_source_paths,
    validate_nonreparse_directory,
    validate_private_attempt_root,
    validate_regular_nonreparse_file,
)
from weather.execution_host import (
    current_execution_principal_id,
    require_current_capture_execution_assignment,
    require_current_portable_execution_assignment,
)
from weather.schema_registry import schema_version
SPEC_SCHEMA_VERSION = schema_version("international_live_fixed_scope_seal_spec")
RECEIPT_SCHEMA_VERSION = schema_version("international_live_fixed_scope_seal")
INVENTORY_SCHEMA_VERSION = schema_version("international_live_fixed_scope_inventory")
EXECUTION_SCHEMA_VERSION = schema_version("international_live_fixed_scope_execution")
REQUIRED_INTERRUPT_CLEANUP_ANCESTOR = "da32c0895bb5b40c842b35232ff266c7968d4439"
MAX_CANDIDATE_AGE_SECONDS = 300
MAX_RUN_WINDOW_SECONDS = 30 * 60
MAX_STAGE1_ORDER_NOTIONAL_PUSD = Decimal("10")
MAX_OPERATOR_BUDGET_PUSD = Decimal("100")
FIRST_TEST_REQUESTED_BUDGET_PUSD = Decimal("10")
FIRST_TEST_WALLET_CAP_PUSD = Decimal("100")
FIRST_SESSION_CREDENTIAL_MODE = "verify_existing_exact"
CREDENTIAL_RECEIPT_MAX_AGE_SECONDS = 2 * 60 * 60
REMOTE_MASTER_REF = "refs/heads/master"
PORTABLE_EXECUTION_AUTHORIZED_TOPIC_BRANCH = (
    "codex/portable-execution-host-clean-20260827"
)
PORTABLE_EXECUTION_AUTHORIZED_TOPIC_REF = (
    f"refs/heads/{PORTABLE_EXECUTION_AUTHORIZED_TOPIC_BRANCH}"
)
CANONICAL_ORIGIN_URL = "https://github.com/michaelbooth1/weather.git"
REMOTE_PROOF_TIMEOUT_SECONDS = 10
ALLOWED_DIRTY_PATHS = frozenset(
    {
        "config/location_market_events.json",
        "config/locations.json",
    }
)
CONDITION_RE = re.compile(r"^0x[0-9a-f]{64}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_OID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
TOKEN_RE = re.compile(r"^[1-9][0-9]*$")
WORKLOAD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
TEMPLATE_MARKER_RE = re.compile(r"__SEAL_[A-Z0-9_]+__")
STAGES = ("stage0", "stage1_cancel_all", "stage1_dead_man")
PYTHON_TEMPLATE_PATHS = {
    "stage0": "scripts/ops/international_live_templates/stage0.py.tmpl",
    "stage1_cancel_all": "scripts/ops/international_live_templates/stage1_cancel_all.py.tmpl",
    "stage1_dead_man": "scripts/ops/international_live_templates/stage1_cancel_all.py.tmpl",
}
LAUNCHER_TEMPLATE_PATH = "scripts/ops/international_live_templates/fixed_scope_launcher.ps1.tmpl"
WORKLOAD_ADMISSION_PATH = "scripts/ops/workload_admission.ps1"
WINDOWS_JOB_HELPER_PATH = "scripts/ops/windows_kill_on_close_job.ps1"
EXECUTION_HOST_ASSIGNMENT_PATH = "config/international_live_execution_host.json"
SDK_OVERLAY_MANIFEST_PATH = "scripts/ops/international_live_templates/sdk_overlay_manifest.json"
SDK_OVERLAY_MODULE_PATH = "src/weather/market/live_sdk_overlay.py"
GEOGRAPHIC_ELIGIBILITY_MODULE_PATH = (
    "src/weather/market/mm_geographic_eligibility.py"
)
LIVE_SOURCE_PATHS = {
    "stage0": (
        "src/weather/market/mm_live_pilot_cli.py",
        "src/weather/market/mm_live_bootstrap.py",
        "src/weather/market/mm_live_candidate_cli.py",
        GEOGRAPHIC_ELIGIBILITY_MODULE_PATH,
        "src/weather/market/mm_credentials.py",
        "src/weather/market/mm_official_adapter.py",
        "src/weather/market/mm_official_transport.py",
        "src/weather/market/mm_user_stream.py",
        SDK_OVERLAY_MODULE_PATH,
        SDK_OVERLAY_MANIFEST_PATH,
        *STATUS_ATTESTATION_SOURCE_PATHS,
    ),
    "stage1_cancel_all": (
        "src/weather/market/mm_live_pilot_cli.py",
        "src/weather/market/mm_live_bootstrap.py",
        "src/weather/market/mm_live_lifecycle_probe.py",
        "src/weather/market/mm_live_candidate_cli.py",
        GEOGRAPHIC_ELIGIBILITY_MODULE_PATH,
        "src/weather/market/mm_credentials.py",
        "src/weather/market/mm_official_adapter.py",
        "src/weather/market/mm_official_transport.py",
        "src/weather/market/mm_user_stream.py",
        SDK_OVERLAY_MODULE_PATH,
        SDK_OVERLAY_MANIFEST_PATH,
        *STATUS_ATTESTATION_SOURCE_PATHS,
    ),
    "stage1_dead_man": (
        "src/weather/market/mm_live_pilot_cli.py",
        "src/weather/market/mm_live_bootstrap.py",
        "src/weather/market/mm_live_lifecycle_probe.py",
        "src/weather/market/mm_live_candidate_cli.py",
        GEOGRAPHIC_ELIGIBILITY_MODULE_PATH,
        "src/weather/market/mm_credentials.py",
        "src/weather/market/mm_official_adapter.py",
        "src/weather/market/mm_official_transport.py",
        "src/weather/market/mm_user_stream.py",
        SDK_OVERLAY_MODULE_PATH,
        SDK_OVERLAY_MANIFEST_PATH,
        *STATUS_ATTESTATION_SOURCE_PATHS,
    ),
}
LIVE_SOURCE_PATHS = {
    stage: tuple(
        sorted(
            set(paths)
            | set(repository_python_source_paths(REPO_ROOT))
            | {EXECUTION_HOST_ASSIGNMENT_PATH, WINDOWS_JOB_HELPER_PATH}
        )
    )
    for stage, paths in LIVE_SOURCE_PATHS.items()
}

INPUT_LAYOUTS = {
    "stage0": {
        "identity": "inputs/stage0-identity.json",
        "scope_plan": "inputs/stage0-scope-plan.json",
        "accepted_economics_snapshot": (
            "inputs/stage0-accepted-economics-snapshot.json"
        ),
        "economics_drift_report": "inputs/stage0-economics-drift-report.json",
        "credential_import_receipt": None,
        "credential_reference_manifest": None,
    },
    "stage1_cancel_all": {
        "identity": "inputs/stage1-identity.json",
        "bootstrap": "stage0/bootstrap.json",
        "stage0_receipt": "stage0/command-receipt.json",
        "stage0_seal_receipt": "seal/stage0-seal-receipt.json",
        "stage0_run_receipt": "session/stage0-run-receipt.json",
        "stage0_run_receipt_sidecar": "session/stage0-run-receipt.json.sha256",
        "stage0_wrapper_execution_receipt": "stage0/wrapper-execution-receipt.json",
        "candidate_plan": "inputs/stage1-cancel-all-candidate.json",
        "accepted_economics_snapshot": (
            "inputs/stage1-cancel-all-accepted-economics-snapshot.json"
        ),
        "economics_drift_report": (
            "inputs/stage1-cancel-all-economics-drift-report.json"
        ),
        "credential_import_receipt": None,
        "credential_reference_manifest": None,
    },
    "stage1_dead_man": {
        "identity": "inputs/stage1-dead-man-identity.json",
        "bootstrap": "stage0/bootstrap.json",
        "stage0_receipt": "stage0/command-receipt.json",
        "stage0_seal_receipt": "seal/stage0-seal-receipt.json",
        "stage0_run_receipt": "session/stage0-run-receipt.json",
        "stage0_run_receipt_sidecar": "session/stage0-run-receipt.json.sha256",
        "stage0_wrapper_execution_receipt": "stage0/wrapper-execution-receipt.json",
        "candidate_plan": "inputs/stage1-dead-man-candidate.json",
        "accepted_economics_snapshot": (
            "inputs/stage1-dead-man-accepted-economics-snapshot.json"
        ),
        "economics_drift_report": (
            "inputs/stage1-dead-man-economics-drift-report.json"
        ),
        "credential_import_receipt": None,
        "credential_reference_manifest": None,
        "cancel_all_seal_receipt": "seal/stage1-cancel-all-seal-receipt.json",
        "cancel_all_run_receipt": "session/stage1_cancel_all-run-receipt.json",
        "cancel_all_run_receipt_sidecar": (
            "session/stage1_cancel_all-run-receipt.json.sha256"
        ),
        "cancel_all_wrapper_execution_receipt": (
            "stage1-cancel-all/wrapper-execution-receipt.json"
        ),
        "cancel_all_command_receipt": "stage1-cancel-all/command-receipt.json",
        "cancel_all_result": "stage1-cancel-all/result.json",
        "cancel_all_lifecycle_journal": "stage1-cancel-all/lifecycle.jsonl",
    },
}

OUTPUT_LAYOUTS = {
    "stage0": {
        "python_wrapper": "wrappers/stage0.py",
        "launcher": "wrappers/stage0.ps1",
        "doctor_receipt": "stage0/doctor-receipt.json",
        "geography_precredential_receipt": (
            "stage0/geography-precredential-receipt.json"
        ),
        "geography_premutation_receipt": (
            "stage0/geography-premutation-receipt.json"
        ),
        "bootstrap": "stage0/bootstrap.json",
        "command_receipt": "stage0/command-receipt.json",
        "user_stream_journal": "stage0/user-stream.jsonl",
        "wrapper_execution_receipt": "stage0/wrapper-execution-receipt.json",
        "seal_receipt": "seal/stage0-seal-receipt.json",
        "seal_receipt_sidecar": "seal/stage0-seal-receipt.json.sha256",
    },
    "stage1_cancel_all": {
        "python_wrapper": "wrappers/stage1-cancel-all.py",
        "launcher": "wrappers/stage1-cancel-all.ps1",
        "doctor_receipt": "stage1-cancel-all/doctor-receipt.json",
        "geography_precredential_receipt": (
            "stage1-cancel-all/geography-precredential-receipt.json"
        ),
        "geography_presubmit_receipt": (
            "stage1-cancel-all/geography-presubmit-receipt.json"
        ),
        "result": "stage1-cancel-all/result.json",
        "command_receipt": "stage1-cancel-all/command-receipt.json",
        "user_stream_journal": "stage1-cancel-all/user-stream.jsonl",
        "lifecycle_journal": "stage1-cancel-all/lifecycle.jsonl",
        "wrapper_execution_receipt": (
            "stage1-cancel-all/wrapper-execution-receipt.json"
        ),
        "seal_receipt": "seal/stage1-cancel-all-seal-receipt.json",
        "seal_receipt_sidecar": (
            "seal/stage1-cancel-all-seal-receipt.json.sha256"
        ),
    },
    "stage1_dead_man": {
        "python_wrapper": "wrappers/stage1-dead-man.py",
        "launcher": "wrappers/stage1-dead-man.ps1",
        "doctor_receipt": "stage1-dead-man/doctor-receipt.json",
        "geography_precredential_receipt": (
            "stage1-dead-man/geography-precredential-receipt.json"
        ),
        "geography_presubmit_receipt": (
            "stage1-dead-man/geography-presubmit-receipt.json"
        ),
        "result": "stage1-dead-man/result.json",
        "command_receipt": "stage1-dead-man/command-receipt.json",
        "user_stream_journal": "stage1-dead-man/user-stream.jsonl",
        "lifecycle_journal": "stage1-dead-man/lifecycle.jsonl",
        "wrapper_execution_receipt": (
            "stage1-dead-man/wrapper-execution-receipt.json"
        ),
        "seal_receipt": "seal/stage1-dead-man-seal-receipt.json",
        "seal_receipt_sidecar": "seal/stage1-dead-man-seal-receipt.json.sha256",
    },
}


class SealError(RuntimeError):
    """Raised when a public sealing prerequisite does not pass exactly."""


GitRunner = Callable[[Path, Sequence[str]], subprocess.CompletedProcess[str]]
PowerShellParser = Callable[[str], None]
SdkValidator = Callable[[str | Path, str], Mapping[str, Any]]


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _canonical_payload_sha256(payload: Mapping[str, Any], *, omit: str) -> str:
    material = {key: value for key, value in payload.items() if key != omit}
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _read_json_object(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SealError(f"{label} is not a readable JSON object") from exc
    if not isinstance(payload, dict):
        raise SealError(f"{label} is not a JSON object")
    return payload, raw


def _validate_geography_artifact(
    artifact: Any,
    *,
    expected_path: Path,
) -> bool:
    if not isinstance(artifact, Mapping):
        return False
    path = Path(str(artifact.get("path") or "")).resolve()
    expected = expected_path.resolve()
    try:
        payload, _raw = _read_json_object(path, label="geographic eligibility receipt")
        validate_geographic_eligibility_receipt(
            payload,
            require_fresh=False,
        )
    except (OSError, SealError, GeographicEligibilityError):
        return False
    return (
        path == expected
        and path.is_file()
        and _sha256_file(path) == artifact.get("sha256")
    )


def _require_exact_keys(
    value: Any,
    expected: set[str],
    *,
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SealError(f"{label} must be an object")
    observed = set(value)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise SealError(f"{label} keys differ (missing={missing}, extra={extra})")
    return value


def _require_sha256(value: Any, *, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if SHA256_RE.fullmatch(normalized) is None:
        raise SealError(f"{label} is not a lowercase SHA-256")
    return normalized


def _require_git_oid(value: Any, *, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if GIT_OID_RE.fullmatch(normalized) is None:
        raise SealError(f"{label} is not a supported Git object id")
    return normalized


def _require_absolute_path(value: Any, *, label: str) -> Path:
    path = Path(str(value or ""))
    if not path.is_absolute():
        raise SealError(f"{label} must be an absolute path")
    return path.resolve()


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(
        str(right.resolve())
    )


def _is_within(root: Path, path: Path) -> bool:
    root_text = os.path.normcase(str(root.resolve()))
    path_text = os.path.normcase(str(path.resolve()))
    try:
        return os.path.commonpath((root_text, path_text)) == root_text
    except ValueError:
        return False


def _parse_aware(value: Any, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise SealError(f"{label} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SealError(f"{label} must be timezone-aware")
    return parsed


def _parse_decimal(value: Any, *, label: str) -> Decimal:
    if isinstance(value, bool):
        raise SealError(f"{label} is not numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SealError(f"{label} is not numeric") from exc
    if not parsed.is_finite():
        raise SealError(f"{label} is not finite")
    return parsed


def _default_git_runner(
    root: Path,
    args: Sequence[str],
) -> subprocess.CompletedProcess[str]:
    live_remote = bool(args) and args[0] == "ls-remote"
    if live_remote:
        assert_no_ambient_proxy_configuration()
    git = canonical_git_executable()
    command = [
        str(git),
        "-c",
        "credential.helper=",
        "-c",
        "credential.interactive=false",
        "-c",
        f"core.hooksPath={os.devnull}",
        "-C",
        str(root),
        *args,
    ]
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
        and key.upper() not in NETWORK_REDIRECT_ENVIRONMENT_KEYS
        and key.upper() != MARKET_REGISTRY_OVERRIDE_ENVIRONMENT_KEY
    }
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GCM_INTERACTIVE": "Never",
        }
    )
    try:
        result = subprocess.run(
            command,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=REMOTE_PROOF_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        result = subprocess.CompletedProcess(command, 124, "", "")
    if live_remote:
        assert_no_ambient_proxy_configuration()
    return result


def _git(
    runner: GitRunner,
    root: Path,
    *args: str,
    allowed: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[str]:
    result = runner(root, list(args))
    if result.returncode not in allowed:
        raise SealError(f"Git public preflight failed: {' '.join(args)}")
    return result


def _git_text(runner: GitRunner, root: Path, *args: str) -> str:
    return _git(runner, root, *args).stdout.strip()


def _remote_ref_oids(
    runner: GitRunner,
    root: Path,
    refs: Sequence[str],
) -> dict[str, str]:
    expected_refs = tuple(dict.fromkeys(str(ref) for ref in refs))
    if not expected_refs or any(
        not ref.startswith("refs/heads/") or ref == "refs/heads/"
        for ref in expected_refs
    ):
        raise SealError("live origin ref proof request is invalid")
    raw = _git_text(
        runner,
        root,
        "ls-remote",
        "--exit-code",
        "--refs",
        CANONICAL_ORIGIN_URL,
        *expected_refs,
    )
    rows = [line.split() for line in raw.splitlines() if line.strip()]
    parsed: dict[str, str] = {}
    for row in rows:
        if (
            len(row) != 2
            or row[1] not in expected_refs
            or row[1] in parsed
            or GIT_OID_RE.fullmatch(row[0].lower()) is None
        ):
            raise SealError("live origin ref proof is malformed or ambiguous")
        parsed[row[1]] = row[0].lower()
    if set(parsed) != set(expected_refs):
        raise SealError("live origin ref proof is incomplete or ambiguous")
    return parsed


def _remote_master_oid(runner: GitRunner, root: Path) -> str:
    """Return the live canonical master tip for compatibility callers."""

    return _remote_ref_oids(runner, root, (REMOTE_MASTER_REF,))[REMOTE_MASTER_REF]


def _remote_branch_ref(branch: str) -> str:
    return f"refs/heads/{branch}"


def _local_branch_ref(branch: str) -> str:
    return f"refs/heads/{branch}"


def _cached_origin_branch_ref(branch: str) -> str:
    return f"refs/remotes/origin/{branch}"


def _branch_is_authorized(execution_host_profile: str, branch: str) -> bool:
    if execution_host_profile == CAPTURE_COLOCATED_HOST_PROFILE:
        return branch == "master"
    if execution_host_profile == PORTABLE_EXECUTION_HOST_PROFILE:
        return branch in {
            "master",
            PORTABLE_EXECUTION_AUTHORIZED_TOPIC_BRANCH,
        }
    return False


def _require_authorized_branch(execution_host_profile: str, branch: str) -> None:
    if execution_host_profile not in EXECUTION_HOST_PROFILES:
        raise SealError("execution host profile is unsupported")
    if _branch_is_authorized(execution_host_profile, branch):
        return
    if execution_host_profile == CAPTURE_COLOCATED_HOST_PROFILE:
        raise SealError("capture-colocated sealing is restricted to production master")
    raise SealError(
        "portable sealing is restricted to production master or the exact authorized "
        "portable topic branch"
    )


def _worktree_policy_clean(
    execution_host_profile: str,
    status_lines: Sequence[str],
) -> bool:
    if any(line[:2] == "??" for line in status_lines):
        return False
    dirty = {line[3:].replace("\\", "/") for line in status_lines}
    if execution_host_profile == PORTABLE_EXECUTION_HOST_PROFILE:
        return not dirty
    return (
        execution_host_profile == CAPTURE_COLOCATED_HOST_PROFILE
        and dirty.issubset(ALLOWED_DIRTY_PATHS)
    )


def _default_powershell_parser(source: str) -> None:
    powershell = canonical_windows_powershell()
    encoded = __import__("base64").b64encode(source.encode("utf-8")).decode("ascii")
    command = (
        "$tokens=$null;$errors=$null;"
        f"$s=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}'));"
        "[void][System.Management.Automation.Language.Parser]::ParseInput("
        "$s,[ref]$tokens,[ref]$errors);"
        "if($errors.Count -ne 0){exit 1};exit 0"
    )
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SealError("generated launcher failed PowerShell AST parsing")


def _default_sdk_validator(
    manifest_path: str | Path,
    expected_manifest_sha256: str,
) -> Mapping[str, Any]:
    from weather.market.live_sdk_overlay import validate_live_sdk_overlay

    return validate_live_sdk_overlay(manifest_path, expected_manifest_sha256)


def _verify_git_state(
    production: Mapping[str, Any],
    *,
    execution_host_profile: str,
    git_runner: GitRunner,
) -> dict[str, Any]:
    root = Path(str(production["root"])).resolve()
    reviewed_git = validate_regular_nonreparse_file(production["git_executable"])
    canonical_git = canonical_git_executable()
    if (
        not _same_path(reviewed_git, canonical_git)
        or _sha256_file(reviewed_git) != production["git_executable_sha256"]
    ):
        raise SealError("reviewed Git executable is not the exact canonical binary")
    expected_commit = _require_git_oid(production["commit"], label="production.commit")
    expected_tree = _require_git_oid(production["tree"], label="production.tree")
    expected_branch = str(production["branch"] or "")
    _require_authorized_branch(execution_host_profile, expected_branch)
    local_branch_ref = _local_branch_ref(expected_branch)
    cached_origin_branch_ref = _cached_origin_branch_ref(expected_branch)
    remote_branch_ref = _remote_branch_ref(expected_branch)
    origin_url = _git_text(
        git_runner, root, "config", "--local", "--get", "remote.origin.url"
    )
    push_url = _git(
        git_runner,
        root,
        "config",
        "--local",
        "--get-all",
        "remote.origin.pushurl",
        allowed=(0, 1),
    )
    local_config_names = _git(
        git_runner,
        root,
        "config",
        "--local",
        "--name-only",
        "--list",
    ).stdout.splitlines()
    forbidden_prefixes = (
        "url.",
        "include.",
        "includeif.",
        "http.",
        "credential.",
        "core.sshcommand",
        "remote.origin.proxy",
    )
    if (
        origin_url != CANONICAL_ORIGIN_URL
        or push_url.stdout.strip()
        or any(name.casefold().startswith(forbidden_prefixes) for name in local_config_names)
    ):
        raise SealError("production Git remote or local trust configuration is not exact")
    remote_refs = _remote_ref_oids(
        git_runner,
        root,
        (REMOTE_MASTER_REF, remote_branch_ref),
    )
    facts = {
        "git_executable": str(reviewed_git),
        "git_executable_sha256": _sha256_file(reviewed_git),
        "origin_url": origin_url,
        "object_format": _git_text(
            git_runner, root, "rev-parse", "--show-object-format"
        ).lower(),
        "head": _git_text(git_runner, root, "rev-parse", "HEAD").lower(),
        "local_branch_tip": _git_text(
            git_runner, root, "rev-parse", local_branch_ref
        ).lower(),
        "cached_origin_branch_tip": _git_text(
            git_runner, root, "rev-parse", cached_origin_branch_ref
        ).lower(),
        "remote_branch_tip": remote_refs[remote_branch_ref],
        "remote_branch_ref": remote_branch_ref,
        "local_master": _git_text(
            git_runner, root, "rev-parse", "refs/heads/master"
        ).lower(),
        "cached_origin_master": _git_text(
            git_runner, root, "rev-parse", "refs/remotes/origin/master"
        ).lower(),
        "remote_master": remote_refs[REMOTE_MASTER_REF],
        "remote_master_ref": REMOTE_MASTER_REF,
        "tree": _git_text(git_runner, root, "rev-parse", "HEAD^{tree}").lower(),
        "branch": _git_text(git_runner, root, "branch", "--show-current"),
    }
    expected_oid_length = {"sha1": 40, "sha256": 64}.get(facts["object_format"])
    if expected_oid_length is None or any(
        len(value) != expected_oid_length
        for value in (expected_commit, expected_tree)
    ):
        raise SealError("reviewed Git object ids do not match the repository format")
    if not (
        facts["head"]
        == facts["local_branch_tip"]
        == facts["cached_origin_branch_tip"]
        == facts["remote_branch_tip"]
        == expected_commit
    ):
        raise SealError(
            "production HEAD/local branch/cached origin branch/live origin branch does "
            "not match the reviewed commit"
        )
    if facts["branch"] != expected_branch:
        raise SealError("checked-out production branch changed from the reviewed branch")
    if not (
        facts["local_master"]
        == facts["cached_origin_master"]
        == facts["remote_master"]
    ):
        raise SealError("local, cached-origin, and live origin master are not synchronized")
    master_ancestry = _git(
        git_runner,
        root,
        "merge-base",
        "--is-ancestor",
        facts["remote_master"],
        expected_commit,
        allowed=(0, 1),
    )
    facts["live_remote_master_equal"] = True
    facts["live_remote_master_ancestor"] = master_ancestry.returncode == 0
    facts["live_remote_branch_equal"] = True
    if master_ancestry.returncode != 0:
        raise SealError("live origin master is not an ancestor of the reviewed branch tip")
    if facts["tree"] != expected_tree:
        raise SealError("production tree or branch does not match the reviewed target")
    ancestry = _git(
        git_runner,
        root,
        "merge-base",
        "--is-ancestor",
        REQUIRED_INTERRUPT_CLEANUP_ANCESTOR,
        expected_commit,
        allowed=(0, 1),
    )
    if ancestry.returncode != 0:
        raise SealError("interrupt-cleanup hardening is not an ancestor of production")
    status_lines = [
        line
        for line in _git(
            git_runner,
            root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ).stdout.splitlines()
        if line.strip()
    ]
    if any(line[:2] == "??" for line in status_lines):
        raise SealError("production worktree has an untracked nonignored path")
    dirty = {line[3:].replace("\\", "/") for line in status_lines}
    if not _worktree_policy_clean(execution_host_profile, status_lines):
        if execution_host_profile == PORTABLE_EXECUTION_HOST_PROFILE and dirty:
            raise SealError("portable production worktree must be completely clean")
        raise SealError("production worktree has unexpected tracked changes")
    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        result = _git(
            git_runner,
            root,
            "rev-parse",
            "-q",
            "--verify",
            marker,
            allowed=(0, 1),
        )
        if result.returncode == 0:
            raise SealError("production has an in-progress Git operation")
    return facts


def _validate_candidate(
    path: Path,
    *,
    target_date: str,
    condition_id: str,
    token_id: str,
    execution_host_profile: str,
    now: datetime,
    run_stop: datetime,
) -> dict[str, Any]:
    payload, raw = _read_json_object(path, label="candidate plan")
    try:
        canonical_gate = load_stage1_candidate_gate(
            path,
            target_date,
            expected_condition_id=condition_id,
            expected_token_id=token_id,
            now=now,
        )
    except RuntimeError as exc:
        raise SealError("candidate plan failed the canonical gate") from exc
    selected = payload.get("selected")
    if not isinstance(selected, dict):
        raise SealError("candidate plan has no selected scope")
    paper = selected.get("paper_quote_proof")
    intent = selected.get("stage1_intent")
    policy = payload.get("selection_policy")
    economics_acceptance = payload.get("economics_acceptance")
    substrate = payload.get("substrate_preflight")
    if not isinstance(paper, dict) or not isinstance(intent, dict) or not isinstance(
        policy, dict
    ):
        raise SealError("candidate plan omits paper, intent, or policy evidence")
    if not isinstance(economics_acceptance, dict):
        raise SealError("candidate plan omits economics acceptance evidence")
    expected_scope = policy.get("expected_bootstrap_scope")
    if not isinstance(expected_scope, dict):
        raise SealError("candidate plan is not constrained to a bootstrap scope")
    created = _parse_aware(payload.get("created_at_utc"), label="candidate created_at")
    expires = _parse_aware(payload.get("expires_at_utc"), label="candidate expires_at")
    paper_generated = _parse_aware(
        paper.get("generated_at_utc"), label="paper quote generated_at"
    )
    paper_expires = _parse_aware(
        paper.get("expires_at_utc"), label="paper quote expires_at"
    )
    accepted_at = _parse_aware(
        economics_acceptance.get("accepted_at_utc"),
        label="economics accepted_at",
    )
    drift_generated = _parse_aware(
        economics_acceptance.get("drift_generated_at_utc"),
        label="economics drift generated_at",
    )
    paper_ttl = _parse_decimal(
        paper.get("quote_ttl_seconds"), label="paper quote TTL"
    )
    expected_paper_expiry = paper_generated + timedelta(seconds=float(paper_ttl))
    try:
        substrate_gate = validate_candidate_substrate_binding(
            substrate,
            target_date=target_date,
            market_id=str(paper.get("market_id") or ""),
            created_at=payload.get("created_at_utc"),
            now=now,
        )
        substrate_expires = _parse_aware(
            substrate_gate["expires_at_utc"],
            label="substrate preflight expires_at",
        )
    except RuntimeError as exc:
        raise SealError("candidate substrate preflight binding failed") from exc
    expected_effective_expiry = min(
        created + timedelta(seconds=MAX_CANDIDATE_AGE_SECONDS),
        paper_expires,
        substrate_expires,
    )
    now_utc = now.astimezone(timezone.utc)
    stop_utc = run_stop.astimezone(timezone.utc)
    economics_id = str(payload.get("exchange_economics_snapshot_id") or "")
    economics_hash = str(payload.get("exchange_economics_sha256") or "")
    market_id = str(paper.get("market_id") or "")
    market = MARKET_REGISTRY.get(market_id)
    try:
        required_acceptance = economics_acceptance_acknowledgment(
            target_date,
            condition_id,
            token_id,
            accepted_snapshot_file_sha256=economics_acceptance.get(
                "accepted_snapshot_file_sha256"
            ),
            drift_report_file_sha256=economics_acceptance.get(
                "drift_report_file_sha256"
            ),
        )
    except RuntimeError:
        required_acceptance = ""
    checks = {
        "schema": payload.get("schema_version") == CANDIDATE_SCHEMA_VERSION,
        "status": payload.get("status") == "PASS",
        "semantic_hash": payload.get("plan_sha256")
        == _canonical_payload_sha256(payload, omit="plan_sha256"),
        "canonical_gate": (
            canonical_gate.get("plan_sha256") == _sha256_bytes(raw)
            and canonical_gate.get("semantic_plan_sha256")
            == payload.get("plan_sha256")
        ),
        "substrate_preflight": (
            substrate_gate.get("accepted_snapshot_file_sha256")
            == economics_acceptance.get("accepted_snapshot_file_sha256")
            and substrate_gate.get("economics_drift_report_file_sha256")
            == economics_acceptance.get("drift_report_file_sha256")
        ),
        "non_authorizing": payload.get("selection_is_trading_authorization") is False,
        "economics_identity": (
            len(economics_hash) == 32
            and all(character in "0123456789abcdef" for character in economics_hash)
            and economics_id == f"xecon-{economics_hash[:16]}"
        ),
        "economics_acceptance": (
            set(economics_acceptance) == ECONOMICS_ACCEPTANCE_KEYS
            and economics_acceptance.get("accepted_snapshot_id") == economics_id
            and economics_acceptance.get("accepted_snapshot_sha256")
            == economics_hash
            and economics_acceptance.get("drift_status") == "PASS"
            and economics_acceptance.get("rescore_required") is False
            and economics_acceptance.get(
                "operator_acknowledgment_matches_candidate"
            )
            is True
            and bool(required_acceptance)
            and economics_acceptance.get("required_operator_acknowledgment")
            == required_acceptance
            and economics_acceptance.get("operator_acknowledgment")
            == required_acceptance
            and accepted_at.astimezone(timezone.utc)
            <= drift_generated.astimezone(timezone.utc)
            <= created.astimezone(timezone.utc)
        ),
        "target_date": payload.get("target_date") == target_date,
        "market_identity": (
            market is not None
            and str(selected.get("location_id") or "") == market_id
        ),
        "scope": str(selected.get("condition_id") or "").lower() == condition_id
        and str(selected.get("token_id") or "") == token_id,
        "constrained_scope": str(expected_scope.get("condition_id") or "").lower()
        == condition_id
        and str(expected_scope.get("token_id") or "") == token_id,
        "paper_scope": str(paper.get("condition_id") or "").lower() == condition_id
        and str(paper.get("token_id") or "") == token_id,
        "paper_permission": paper.get("quote_permission") is True
        and paper.get("live_trade_permission") is False,
        "paper_ttl": (
            Decimal("0") < paper_ttl <= MAX_PAPER_QUOTE_TTL_SECONDS
            and (
                execution_host_profile == PORTABLE_EXECUTION_HOST_PROFILE
                or paper_ttl <= Decimal("120")
            )
        ),
        "paper_expiry": paper_expires == expected_paper_expiry,
        "effective_expiry": expires == expected_effective_expiry,
        "created_before_seal": created.astimezone(timezone.utc) <= now_utc,
        "paper_before_plan": paper_generated.astimezone(timezone.utc)
        <= created.astimezone(timezone.utc),
        "current": now_utc <= expires.astimezone(timezone.utc),
        "window_within_ttl": stop_utc <= expires.astimezone(timezone.utc),
        "intent": intent.get("side") == "BUY"
        and intent.get("post_only") is True,
    }
    price = _parse_decimal(intent.get("price"), label="candidate intent price")
    size = _parse_decimal(intent.get("size"), label="candidate intent size")
    notional = _parse_decimal(
        intent.get("notional_pusd"), label="candidate intent notional"
    )
    tick = _parse_decimal(selected.get("tick_size"), label="candidate tick size")
    minimum = _parse_decimal(
        selected.get("order_min_size"), label="candidate order minimum"
    )
    checks["minimum_tick_intent"] = (
        Decimal("0") < price < Decimal("1")
        and price == tick
        and size == minimum
        and Decimal("0") < notional <= MAX_STAGE1_ORDER_NOTIONAL_PUSD
        and notional == price * size
    )
    missing = sorted(name for name, passed in checks.items() if not passed)
    if missing:
        raise SealError("candidate plan gate failed: " + ", ".join(missing))
    return {
        "path": str(path),
        "sha256": _sha256_bytes(raw),
        "semantic_plan_sha256": payload["plan_sha256"],
        "created_at_utc": created.astimezone(timezone.utc).isoformat(),
        "expires_at_utc": expires.astimezone(timezone.utc).isoformat(),
        "paper_quote_expires_at_utc": paper_expires.astimezone(timezone.utc).isoformat(),
        "economics_snapshot_id": economics_id,
        "economics_snapshot_sha256": economics_hash,
        "economics_acceptance": dict(economics_acceptance),
        "remaining_seconds_at_seal": (
            expires.astimezone(timezone.utc) - now_utc
        ).total_seconds(),
        "market_id": market_id,
        "market_timezone": market.timezone,
    }


def _validate_stage0_receipt(
    path: Path,
    *,
    target_date: str,
    condition_id: str,
    token_id: str,
    budget: Decimal,
) -> None:
    payload, _raw = _read_json_object(path, label="Stage 0 command receipt")
    try:
        observed_budget = Decimal(str(payload.get("requested_budget_pusd")))
    except (InvalidOperation, TypeError, ValueError):
        observed_budget = Decimal("-1")
    checks = (
        payload.get("schema_version") == "mm_live_pilot_command_receipt_v0.2",
        payload.get("status") == "PASS",
        payload.get("command") == "stage0",
        payload.get("target_date") == target_date,
        str(payload.get("condition_id") or "").lower() == condition_id,
        str(payload.get("token_id") or "") == token_id,
        observed_budget == budget,
        isinstance(payload.get("cleanup"), dict)
        and payload["cleanup"].get("ok") is True,
        payload.get("exception_type") is None,
    )
    if not all(checks):
        raise SealError("Stage 0 receipt does not bind the reviewed Stage 1 scope")


def _validate_credential_reference_manifest(path: Path) -> dict[str, Any]:
    payload, _raw = _read_json_object(path, label="credential reference manifest")
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "platform",
            "wallet_type",
            "signature_type",
            "signature_type_id",
            "wallet_address",
            "funder_address",
            "credential_references",
            "public_environment",
            "secret_values_retained",
            "ignored_relayers_rpc_and_self_assertions",
        },
        label="credential reference manifest",
    )
    reference_names = {
        "POLYMARKET_API_KEY_STORAGE_REF",
        "POLYMARKET_API_SECRET_STORAGE_REF",
        "POLYMARKET_API_PASSPHRASE_STORAGE_REF",
        "POLYMARKET_PRIVATE_KEY_STORAGE_REF",
    }
    references = _require_exact_keys(
        payload["credential_references"],
        reference_names,
        label="credential references",
    )
    public = _require_exact_keys(
        payload["public_environment"],
        {"POLYMARKET_FUNDER_ADDRESS"},
        label="credential public environment",
    )
    if (
        payload["schema_version"] != "mm_live_credential_reference_manifest_v0.1"
        or payload["platform"] != "polymarket_global"
        or payload["secret_values_retained"] is not False
        or dict(references) != EXPECTED_CREDENTIAL_REFERENCES
        or re.fullmatch(r"0x[0-9a-fA-F]{40}", str(payload["funder_address"] or ""))
        is None
        or str(public["POLYMARKET_FUNDER_ADDRESS"]).lower()
        != str(payload["funder_address"]).lower()
        or payload["ignored_relayers_rpc_and_self_assertions"] is not True
        or (
            payload["wallet_type"],
            payload["signature_type"],
            payload["signature_type_id"],
        )
        not in {
            ("gnosis_safe", "POLY_GNOSIS_SAFE", 2),
            ("deposit_wallet", "POLY_1271", 3),
        }
        or re.fullmatch(r"0x[0-9a-fA-F]{40}", str(payload["wallet_address"] or ""))
        is None
        or str(payload["wallet_address"]).lower()
        == str(payload["funder_address"]).lower()
    ):
        raise SealError("credential reference manifest is not the exact public contract")
    return dict(payload)


def _validate_credential_import_receipt(
    path: Path,
    *,
    required_mode: str | None = None,
    now: datetime | None = None,
) -> None:
    if required_mode not in {None, FIRST_SESSION_CREDENTIAL_MODE}:
        raise SealError("credential import receipt mode requirement is unsupported")
    payload, _raw = _read_json_object(path, label="credential import receipt")
    common_required = {
        "schema_version",
        "status",
        "platform",
        "source_outside_repository_verified",
        "source_acl_private_confirmed",
        "credential_value_count_expected",
        "credential_value_count_written",
        "credential_values_retained",
        "ignored_source_key_count",
        "checks",
        "missing",
        "rollback_attempted",
        "rollback_ok",
        "source_deletion_required_after_transfer",
    }
    legacy_version = "mm_live_credential_import_receipt_v0.1"
    compare_only_legacy_version = "mm_live_credential_import_receipt_v0.2"
    host_only_legacy_version = "mm_live_credential_import_receipt_v0.3"
    current_version = "mm_live_credential_import_receipt_v0.4"
    version = payload.get("schema_version")
    if version == legacy_version:
        _require_exact_keys(
            payload,
            common_required,
            label="credential import receipt",
        )
        mode_is_exact = payload.get("credential_value_count_written") == 4
    elif version in {
        compare_only_legacy_version,
        host_only_legacy_version,
        current_version,
    }:
        version_fields = set()
        if version in {host_only_legacy_version, current_version}:
            version_fields = {"prepared_at_utc", "execution_host_id"}
        if version == current_version:
            version_fields.add("execution_principal_id")
        _require_exact_keys(
            payload,
            common_required
            | {
                "credential_mode",
                "credential_value_count_existing_exact_verified",
                "credential_store_mutation_attempted",
            }
            | version_fields,
            label="credential import receipt",
        )
        mode = payload.get("credential_mode")
        written = payload.get("credential_value_count_written")
        verified = payload.get("credential_value_count_existing_exact_verified")
        mutation_attempted = payload.get("credential_store_mutation_attempted")
        mode_is_exact = (
            mode == "create_new"
            and type(written) is int
            and written == 4
            and type(verified) is int
            and verified == 0
            and mutation_attempted is True
        ) or (
            mode == FIRST_SESSION_CREDENTIAL_MODE
            and type(written) is int
            and written == 0
            and type(verified) is int
            and verified == 4
            and mutation_attempted is False
        )
    else:
        raise SealError("credential import receipt is not an exact clean PASS")
    checks = payload.get("checks")
    host_binding_ok = version not in {host_only_legacy_version, current_version}
    principal_binding_ok = version != current_version
    freshness_ok = version not in {host_only_legacy_version, current_version}
    if version in {host_only_legacy_version, current_version}:
        try:
            prepared_at = _parse_aware(
                payload.get("prepared_at_utc"),
                label="credential receipt prepared_at_utc",
            )
            current = now or datetime.now().astimezone()
            age_seconds = (
                current.astimezone(timezone.utc)
                - prepared_at.astimezone(timezone.utc)
            ).total_seconds()
            freshness_ok = -5 <= age_seconds <= CREDENTIAL_RECEIPT_MAX_AGE_SECONDS
        except SealError:
            freshness_ok = False
        host_binding_ok = (
            payload.get("execution_host_id") == current_execution_host_id()
        )
        if version == current_version:
            principal_binding_ok = (
                payload.get("execution_principal_id")
                == current_execution_principal_id()
            )
    if (
        payload["status"] != "PASS"
        or payload["platform"] != "polymarket_global"
        or payload["credential_value_count_expected"] != 4
        or not mode_is_exact
        or payload["credential_values_retained"] is not False
        or payload["source_outside_repository_verified"] is not True
        or payload["source_acl_private_confirmed"] is not True
        or payload["source_deletion_required_after_transfer"] is not True
        or payload["rollback_attempted"] is not False
        or payload["rollback_ok"] is not None
        or not isinstance(payload["ignored_source_key_count"], int)
        or not 0 <= payload["ignored_source_key_count"] <= 8
        or (
            version == current_version
            and payload["ignored_source_key_count"] != 0
        )
        or payload["missing"] != []
        or not isinstance(checks, dict)
        or set(checks) != EXPECTED_CREDENTIAL_IMPORT_CHECKS
        or any(value is not True for value in checks.values())
        or not host_binding_ok
        or not principal_binding_ok
        or not freshness_ok
    ):
        raise SealError("credential import receipt is not an exact clean PASS")
    if required_mode == FIRST_SESSION_CREDENTIAL_MODE and not (
        version == current_version
        and payload.get("credential_mode") == FIRST_SESSION_CREDENTIAL_MODE
        and type(payload.get("credential_value_count_written")) is int
        and payload["credential_value_count_written"] == 0
        and type(payload.get("credential_value_count_existing_exact_verified"))
        is int
        and payload["credential_value_count_existing_exact_verified"] == 4
        and payload.get("credential_store_mutation_attempted") is False
    ):
        raise SealError(
            "first-session credential evidence must be fresh v0.4 host/principal-bound "
            "compare-only exact verification with four existing entries and zero mutation"
        )


def _validate_identity(
    path: Path,
    *,
    requested_budget: Decimal,
    expected_reference: Mapping[str, Any],
) -> None:
    payload, _raw = _read_json_object(path, label="Stage 0 identity")
    try:
        wallet_cap = Decimal(str(payload.get("pilot_wallet_max_funding_usdc")))
    except (InvalidOperation, TypeError, ValueError):
        wallet_cap = Decimal("-1")
    from weather.market.mm_credentials import (
        STAGE0_IDENTITY_SCHEMA_VERSION,
        stage0_client_identity_gate,
    )

    gate = stage0_client_identity_gate(
        payload,
        expected_funder=str(expected_reference["funder_address"]),
    )
    if (
        payload.get("schema_version") != STAGE0_IDENTITY_SCHEMA_VERSION
        or payload.get("platform") != "polymarket_global"
        or wallet_cap != FIRST_TEST_WALLET_CAP_PUSD
        or requested_budget != FIRST_TEST_REQUESTED_BUDGET_PUSD
        or requested_budget > wallet_cap
        or gate.get("ok") is not True
        or gate.get("missing") != []
        or not all(value is True for value in (gate.get("checks") or {}).values())
        or payload.get("wallet_type") != expected_reference.get("wallet_type")
        or payload.get("signature_type") != expected_reference.get("signature_type")
        or payload.get("signature_type_id")
        != expected_reference.get("signature_type_id")
    ):
        raise SealError("identity does not bind the 10 pUSD request and 100 pUSD wallet cap")


def _validate_stage0_lineage(
    inputs: Mapping[str, Mapping[str, str]],
    *,
    attempt_root: Path,
    production_tip: str,
    target_date: str,
    condition_id: str,
    token_id: str,
    budget: Decimal,
    execution_host_profile: str,
    execution_host_id: str,
    market_id: str,
    market_timezone: str,
) -> None:
    seal, _raw = _read_json_object(
        Path(inputs["stage0_seal_receipt"]["path"]),
        label="Stage 0 seal receipt",
    )
    execution, _raw = _read_json_object(
        Path(inputs["stage0_wrapper_execution_receipt"]["path"]),
        label="Stage 0 wrapper execution receipt",
    )
    run, _raw = _read_json_object(
        Path(inputs["stage0_run_receipt"]["path"]),
        label="Stage 0 session run receipt",
    )
    command, _raw = _read_json_object(
        Path(inputs["stage0_receipt"]["path"]), label="Stage 0 command receipt"
    )
    reference, _raw = _read_json_object(
        Path(inputs["credential_reference_manifest"]["path"]),
        label="credential reference manifest",
    )
    topology = command.get("credential_topology") or {}
    seal_scope = seal.get("scope") if isinstance(seal.get("scope"), dict) else {}
    seal_production = (
        seal.get("production") if isinstance(seal.get("production"), dict) else {}
    )
    seal_credential = (
        seal.get("credential_import_receipt")
        if isinstance(seal.get("credential_import_receipt"), dict)
        else {}
    )
    seal_reference = (
        seal.get("credential_reference_manifest")
        if isinstance(seal.get("credential_reference_manifest"), dict)
        else {}
    )
    seal_wrapper = seal.get("wrapper") if isinstance(seal.get("wrapper"), dict) else {}
    execution_wrapper = (
        execution.get("wrapper")
        if isinstance(execution.get("wrapper"), dict)
        else {}
    )
    artifacts = (
        execution.get("artifacts")
        if isinstance(execution.get("artifacts"), dict)
        else {}
    )
    bootstrap_artifact = artifacts.get("bootstrap_out") or {}
    command_artifact = artifacts.get("command_receipt_out") or {}
    stream_artifact = artifacts.get("user_stream_journal_out") or {}
    geography_premutation_artifact = (
        artifacts.get("geography_premutation_receipt_out") or {}
    )
    command_geography = command.get("mutation_geographic_eligibility") or {}
    bootstrap, _raw = _read_json_object(
        Path(inputs["bootstrap"]["path"]), label="Stage 0 bootstrap"
    )
    bootstrap_geography = bootstrap.get("mutation_geographic_eligibility") or {}
    premutation_geography, _raw = _read_json_object(
        Path(str(geography_premutation_artifact.get("path") or "")),
        label="Stage 0 pre-mutation geography receipt",
    )
    run_child = run.get("child_execution") or {}
    run_lineage_ok = exact_run_lineage(
        run,
        attempt_root=attempt_root,
        stage="stage0",
        seal=seal,
        seal_path=Path(inputs["stage0_seal_receipt"]["path"]),
        sha256_file=_sha256_file,
    )
    run_sidecar = Path(inputs["stage0_run_receipt_sidecar"]["path"])
    attestations = execution.get("host_attestations")
    expected_flag_hashes = sorted(
        row["sha256"] for row in seal_scope.get("reviewed_status_flags") or []
    )
    expected_credential = inputs["credential_import_receipt"]
    expected_reference = inputs["credential_reference_manifest"]
    try:
        seal_budget = Decimal(str(seal_scope.get("requested_budget_pusd")))
        execution_budget = Decimal(str(execution.get("requested_budget_pusd")))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SealError("Stage 0 lineage has an invalid budget") from exc
    checks = (
        seal.get("schema_version") == RECEIPT_SCHEMA_VERSION,
        seal.get("status") == "PASS",
        seal.get("stage") == "stage0",
        seal_production.get("commit") == production_tip,
        seal_scope.get("target_date") == target_date,
        Path(str(seal_scope.get("attempt_root") or "")).resolve() == attempt_root,
        str(seal_scope.get("condition_id") or "").lower() == condition_id,
        str(seal_scope.get("token_id") or "") == token_id,
        seal_budget == budget,
        seal_scope.get("execution_host_profile") == execution_host_profile,
        seal_scope.get("execution_host_id") == execution_host_id,
        seal_scope.get("market_id") == market_id,
        seal_scope.get("market_timezone") == market_timezone,
        seal_credential.get("path") == expected_credential["path"],
        seal_credential.get("sha256") == expected_credential["sha256"],
        seal_reference.get("path") == expected_reference["path"],
        seal_reference.get("sha256") == expected_reference["sha256"],
        execution.get("schema_version") == EXECUTION_SCHEMA_VERSION,
        execution.get("status") == "PASS",
        execution.get("stage") == "stage0",
        execution.get("phase") == "complete",
        execution.get("credential_values_read_in_memory") is True,
        execution.get("live_mutation_attempted") is True,
        execution.get("order_submit_attempted") is False,
        execution.get("authenticated_exchange_write_attempted") is True,
        execution.get("execution_host_profile") == execution_host_profile,
        execution.get("execution_host_id") == execution_host_id,
        isinstance(attestations, list),
        len(attestations or []) == 3,
        all(
            len(str(row.get("status_json_sha256") or "")) == 64
            and sorted(row.get("status_flag_sha256") or []) == expected_flag_hashes
            and row.get("execution_host_profile") == execution_host_profile
            and row.get("execution_host_id") == execution_host_id
            and bool(row.get("checked_at_local"))
            for row in (attestations or [])
        ),
        execution.get("production_tip") == production_tip,
        execution.get("target_date") == target_date,
        str(execution.get("condition_id") or "").lower() == condition_id,
        str(execution.get("token_id") or "") == token_id,
        execution_budget == budget,
        execution.get("exception_type") is None,
        set(artifacts)
        == {
            "doctor_receipt_out",
            "geography_precredential_receipt_out",
            "geography_premutation_receipt_out",
            "bootstrap_out",
            "command_receipt_out",
            "user_stream_journal_out",
        },
        _validate_geography_artifact(
            artifacts.get("geography_precredential_receipt_out"),
            expected_path=(
                attempt_root
                / OUTPUT_LAYOUTS["stage0"]["geography_precredential_receipt"]
            ),
        ),
        _validate_geography_artifact(
            geography_premutation_artifact,
            expected_path=(
                attempt_root
                / OUTPUT_LAYOUTS["stage0"]["geography_premutation_receipt"]
            ),
        ),
        command_geography.get("path")
        == geography_premutation_artifact.get("path"),
        command_geography.get("sha256")
        == geography_premutation_artifact.get("sha256"),
        bootstrap.get("schema_version") == "mm_platform_bootstrap_v0.4",
        bootstrap_geography.get("status") == "PASS",
        bootstrap_geography.get("eligible") is True,
        len(str(bootstrap_geography.get("receipt_payload_sha256") or "")) == 64,
        bootstrap_geography.get("receipt_payload_sha256")
        == premutation_geography.get("receipt_payload_sha256"),
        seal_wrapper.get("path") == execution_wrapper.get("path"),
        seal_wrapper.get("sha256") == execution_wrapper.get("sha256"),
        bootstrap_artifact.get("path") == inputs["bootstrap"]["path"],
        bootstrap_artifact.get("sha256") == inputs["bootstrap"]["sha256"],
        command_artifact.get("path") == inputs["stage0_receipt"]["path"],
        command_artifact.get("sha256") == inputs["stage0_receipt"]["sha256"],
        bool(stream_artifact.get("path")),
        SHA256_RE.fullmatch(str(stream_artifact.get("sha256") or "")) is not None,
        Path(str(stream_artifact.get("path") or "")).is_file(),
        (
            _sha256_file(Path(str(stream_artifact.get("path"))))
            == stream_artifact.get("sha256")
            if stream_artifact.get("path")
            and Path(str(stream_artifact.get("path"))).is_file()
            else False
        ),
        command.get("credential_values_read_in_memory") is True,
        command.get("exchange_mutation_attempted") is True,
        command.get("order_submit_attempted") is False,
        command.get("authenticated_exchange_write_attempted") is True,
        topology.get("manifest_wallet_address")
        == str(reference.get("wallet_address") or "").lower(),
        set(topology) == CREDENTIAL_TOPOLOGY_KEYS,
        all(value is True for key, value in topology.items() if key != "manifest_wallet_address"),
        run.get("schema_version") == "international_live_session_run_v0.4",
        run.get("status") == "PASS",
        run.get("stage") == "stage0",
        run.get("execution_host_profile") == execution_host_profile,
        run.get("execution_host_id") == execution_host_id,
        run.get("live_mutation_attempted") is True,
        run.get("order_submit_attempted") is False,
        run.get("authenticated_exchange_write_attempted") is True,
        run.get("credential_values_read_in_memory") is True,
        run_child.get("validation") == "PASS",
        run_child.get("status") == "PASS",
        run_child.get("phase") == "complete",
        run_child.get("path") == inputs["stage0_wrapper_execution_receipt"]["path"],
        run_child.get("sha256")
        == inputs["stage0_wrapper_execution_receipt"]["sha256"],
        (run.get("seal_receipt") or {}).get("path")
        == inputs["stage0_seal_receipt"]["path"],
        (run.get("seal_receipt") or {}).get("sha256")
        == inputs["stage0_seal_receipt"]["sha256"],
        run_lineage_ok,
        run_sidecar.read_text(encoding="ascii")
        == (
            f"{inputs['stage0_run_receipt']['sha256']}  "
            f"{Path(inputs['stage0_run_receipt']['path']).name}\n"
        ),
    )
    if not all(checks):
        raise SealError("Stage 0 seal/execution lineage does not bind Stage 1")


def _validate_cancel_all_predecessor(
    inputs: Mapping[str, Mapping[str, str]],
    *,
    attempt_root: Path,
    production_tip: str,
    target_date: str,
    condition_id: str,
    token_id: str,
    budget: Decimal,
    execution_host_profile: str,
    execution_host_id: str,
    market_id: str,
    market_timezone: str,
) -> None:
    payloads = {}
    for role in (
        "cancel_all_seal_receipt",
        "cancel_all_run_receipt",
        "cancel_all_wrapper_execution_receipt",
        "cancel_all_command_receipt",
        "cancel_all_result",
    ):
        payloads[role] = _read_json_object(
            Path(inputs[role]["path"]), label=role
        )[0]
    seal = payloads["cancel_all_seal_receipt"]
    run = payloads["cancel_all_run_receipt"]
    execution = payloads["cancel_all_wrapper_execution_receipt"]
    command = payloads["cancel_all_command_receipt"]
    result = payloads["cancel_all_result"]
    journal_path = Path(inputs["cancel_all_lifecycle_journal"]["path"])
    run_sidecar_path = Path(inputs["cancel_all_run_receipt_sidecar"]["path"])
    child = run.get("child_execution") or {}
    seal_scope = seal.get("scope") or {}
    seal_production = seal.get("production") or {}
    seal_inputs = {
        row.get("role"): row
        for row in (seal.get("inputs") or [])
        if isinstance(row, dict) and row.get("role")
    }
    candidate_record = seal_inputs.get("candidate_plan") or {}
    candidate, _raw = _read_json_object(
        Path(str(candidate_record.get("path") or "")),
        label="cancel-all predecessor candidate plan",
    )
    candidate_selected = candidate.get("selected") or {}
    try:
        candidate_fee_rate = Decimal(str(candidate_selected.get("fee_rate")))
        result_candidate_fee_rate = Decimal(
            str(result.get("candidate_fee_rate"))
        )
        result_current_fee_rate_bps = Decimal(
            str(result.get("current_fee_rate_bps"))
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SealError("cancel-all predecessor fee binding is invalid") from exc
    topology = command.get("credential_topology") or {}
    seal_wrapper = seal.get("wrapper") or {}
    execution_wrapper = execution.get("wrapper") or {}
    artifacts = execution.get("artifacts") or {}
    result_artifact = artifacts.get("result_out") or {}
    command_artifact = artifacts.get("command_receipt_out") or {}
    journal_artifact = artifacts.get("lifecycle_journal_out") or {}
    stream_artifact = artifacts.get("user_stream_journal_out") or {}
    try:
        final_stream_evidence = verify_stage1_user_stream_journal(
            Path(str(stream_artifact.get("path") or "")),
            result,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise SealError(
            "cancel-all predecessor final user-stream evidence is invalid"
        ) from exc
    run_lineage_ok = exact_run_lineage(
        run,
        attempt_root=attempt_root,
        stage="stage1_cancel_all",
        seal=seal,
        seal_path=Path(inputs["cancel_all_seal_receipt"]["path"]),
        sha256_file=_sha256_file,
    )
    checks = (
        seal.get("schema_version") == RECEIPT_SCHEMA_VERSION,
        seal.get("status") == "PASS",
        seal.get("stage") == "stage1_cancel_all",
        seal_production.get("commit") == production_tip,
        seal_scope.get("target_date") == target_date,
        Path(str(seal_scope.get("attempt_root") or "")).resolve() == attempt_root,
        str(seal_scope.get("condition_id") or "").lower() == condition_id,
        str(seal_scope.get("token_id") or "") == token_id,
        float(seal_scope.get("requested_budget_pusd")) == float(budget),
        seal_scope.get("execution_host_profile") == execution_host_profile,
        seal_scope.get("execution_host_id") == execution_host_id,
        seal_scope.get("market_id") == market_id,
        seal_scope.get("market_timezone") == market_timezone,
        seal_scope.get("cancellation_mode") == "cancel_all",
        seal_wrapper.get("path") == execution_wrapper.get("path"),
        seal_wrapper.get("sha256") == execution_wrapper.get("sha256"),
        run.get("schema_version") == "international_live_session_run_v0.4",
        run.get("status") == "PASS",
        run.get("stage") == "stage1_cancel_all",
        run.get("execution_host_profile") == execution_host_profile,
        run.get("execution_host_id") == execution_host_id,
        run.get("live_mutation_attempted") is True,
        run.get("order_submit_attempted") is True,
        run.get("authenticated_exchange_write_attempted") is True,
        run.get("credential_values_read_in_memory") is True,
        child.get("validation") == "PASS",
        child.get("status") == "PASS",
        child.get("phase") == "complete",
        child.get("path")
        == inputs["cancel_all_wrapper_execution_receipt"]["path"],
        child.get("sha256")
        == inputs["cancel_all_wrapper_execution_receipt"]["sha256"],
        (run.get("seal_receipt") or {}).get("path")
        == inputs["cancel_all_seal_receipt"]["path"],
        (run.get("seal_receipt") or {}).get("sha256")
        == inputs["cancel_all_seal_receipt"]["sha256"],
        run.get("candidate_sha256") == result.get("candidate_plan_sha256"),
        run_lineage_ok,
        execution.get("schema_version") == EXECUTION_SCHEMA_VERSION,
        execution.get("status") == "PASS",
        execution.get("stage") == "stage1_cancel_all",
        execution.get("execution_host_profile") == execution_host_profile,
        execution.get("execution_host_id") == execution_host_id,
        execution.get("phase") == "complete",
        execution.get("live_mutation_attempted") is True,
        execution.get("order_submit_attempted") is True,
        execution.get("authenticated_exchange_write_attempted") is True,
        execution.get("credential_values_read_in_memory") is True,
        execution.get("production_tip") == production_tip,
        execution.get("target_date") == target_date,
        str(execution.get("condition_id") or "").lower() == condition_id,
        str(execution.get("token_id") or "") == token_id,
        float(execution.get("requested_budget_pusd")) == float(budget),
        execution.get("exception_type") is None,
        set(artifacts)
        == {
            "doctor_receipt_out",
            "geography_precredential_receipt_out",
            "geography_presubmit_receipt_out",
            "result_out",
            "command_receipt_out",
            "user_stream_journal_out",
            "lifecycle_journal_out",
        },
        _validate_geography_artifact(
            artifacts.get("geography_precredential_receipt_out"),
            expected_path=(
                attempt_root
                / OUTPUT_LAYOUTS["stage1_cancel_all"][
                    "geography_precredential_receipt"
                ]
            ),
        ),
        _validate_geography_artifact(
            artifacts.get("geography_presubmit_receipt_out"),
            expected_path=(
                attempt_root
                / OUTPUT_LAYOUTS["stage1_cancel_all"][
                    "geography_presubmit_receipt"
                ]
            ),
        ),
        result_artifact.get("path") == inputs["cancel_all_result"]["path"],
        result_artifact.get("sha256") == inputs["cancel_all_result"]["sha256"],
        command_artifact.get("path") == inputs["cancel_all_command_receipt"]["path"],
        command_artifact.get("sha256")
        == inputs["cancel_all_command_receipt"]["sha256"],
        journal_artifact.get("path")
        == inputs["cancel_all_lifecycle_journal"]["path"],
        journal_artifact.get("sha256")
        == inputs["cancel_all_lifecycle_journal"]["sha256"],
        bool(stream_artifact.get("path")),
        Path(str(stream_artifact.get("path") or "")).is_file(),
        (
            _sha256_file(Path(str(stream_artifact.get("path"))))
            == stream_artifact.get("sha256")
            if stream_artifact.get("path")
            and Path(str(stream_artifact.get("path"))).is_file()
            else False
        ),
        command.get("schema_version") == "mm_live_pilot_command_receipt_v0.2",
        command.get("status") == "PASS",
        command.get("command") == "stage1",
        command.get("cancellation_mode") == "cancel_all",
        command.get("target_date") == target_date,
        str(command.get("condition_id") or "").lower() == condition_id,
        str(command.get("token_id") or "") == token_id,
        float(command.get("requested_budget_pusd")) == float(budget),
        command.get("credential_values_read_in_memory") is True,
        command.get("exchange_mutation_attempted") is True,
        command.get("order_submit_attempted") is True,
        command.get("authenticated_exchange_write_attempted") is True,
        bool(topology.get("manifest_wallet_address")),
        set(topology) == CREDENTIAL_TOPOLOGY_KEYS,
        all(value is True for key, value in topology.items() if key != "manifest_wallet_address"),
        (command.get("cleanup") or {}).get("ok") is True,
        command.get("exception_type") is None,
        result.get("schema_version") == "mm_live_lifecycle_probe_v0.3",
        result.get("status") == "PASS",
        result.get("cancellation_mode") == "cancel_all",
        str(result.get("condition_id") or "").lower() == condition_id,
        str(result.get("token_id") or "") == token_id,
        result.get("candidate_plan_sha256")
        == (seal_inputs.get("candidate_plan") or {}).get("sha256"),
        result.get("submit_boundary_heartbeat_acknowledged") is True,
        result.get("submit_boundary_market_rules_verified") is True,
        result.get("submit_boundary_geography_before_heartbeat_verified") is True,
        result.get("post_sign_order_placement_boundary_verified") is True,
        result_candidate_fee_rate == candidate_fee_rate,
        result_current_fee_rate_bps == candidate_fee_rate * Decimal("10000"),
        result.get("candidate_neg_risk") is candidate_selected.get("neg_risk"),
        result.get("current_neg_risk") is candidate_selected.get("neg_risk"),
        bool(str(result.get("order_id") or "")),
        result.get("placement_status") == "live",
        result.get("zero_open_orders_verified") is True,
        result.get("zero_positions_verified") is True,
        result.get("no_trade_lifecycle_event_observed") is True,
        result.get("terminal_rest_order_verified") is True,
        result.get("terminal_rest_zero_matched_verified") is True,
        result.get("account_trades_rest_verified") is True,
        result.get("scoped_account_trade_count") == 0,
        result.get("post_cancel_quiescence_seconds") == 2.0,
        result.get("collateral_no_fill_reconciliation_verified") is True,
        len(str(result.get("submit_collateral_snapshot_sha256") or "")) == 64,
        result.get("submit_collateral_snapshot_sha256")
        == result.get("post_cancel_collateral_snapshot_sha256"),
        10 <= float(result.get("submit_collateral_balance_usdc")) <= 100,
        float(result.get("submit_collateral_allowance_usdc")) >= 10,
        result.get("terminal_user_event_observed") is True,
        Path(str(result.get("user_stream_journal_path") or "")).resolve()
        == Path(str(stream_artifact.get("path") or "")).resolve(),
        result.get("user_stream_journal_sha256") == stream_artifact.get("sha256"),
        result.get("cleanup_final_user_stream_journal_sha256")
        == stream_artifact.get("sha256"),
        final_stream_evidence.get("sha256")
        == result.get("user_stream_journal_sha256"),
        final_stream_evidence.get("terminal_stream_stopped_verified") is True,
        type(result.get("user_stream_scoped_order_event_count")) is int,
        result.get("user_stream_scoped_order_event_count") >= 2,
        result.get("cancel_response_present") is True,
        Path(str(result.get("journal_path") or "")).resolve() == journal_path,
        result.get("journal_sha256") == inputs["cancel_all_lifecycle_journal"][
            "sha256"
        ],
        run_sidecar_path.read_text(encoding="ascii")
        == (
            f"{inputs['cancel_all_run_receipt']['sha256']}  "
            f"{Path(inputs['cancel_all_run_receipt']['path']).name}\n"
        ),
    )
    if not all(checks):
        raise SealError("dead-man stage requires a validated cancel-all PASS lineage")


def _replace_once(source: str, marker: str, replacement: str) -> str:
    if source.count(marker) != 1:
        raise SealError(f"template marker is not unique: {marker}")
    return source.replace(marker, replacement, 1)


def _python_literal(value: Any) -> str:
    return json.dumps(value, indent=4, sort_keys=True, ensure_ascii=True)


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _validate_unsealed_template(source: str) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise SealError("repository Python template failed AST parsing") from exc
    sealed_values = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "TEMPLATE_SEALED"
            for target in node.targets
        )
    ]
    if not (
        len(sealed_values) == 1
        and isinstance(sealed_values[0], ast.Constant)
        and sealed_values[0].value is False
    ):
        raise SealError("repository Python template is not inert")
    main = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        ),
        None,
    )
    if main is None:
        raise SealError("repository Python template has no main boundary")
    sealed_calls = [
        node
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_assert_sealed"
    ]
    weather_imports = [
        node
        for node in ast.walk(main)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and (
            (
                isinstance(node, ast.ImportFrom)
                and str(node.module or "").startswith("weather")
            )
            or (
                isinstance(node, ast.Import)
                and any(alias.name.startswith("weather") for alias in node.names)
            )
        )
    ]
    if len(sealed_calls) != 1 or not weather_imports or sealed_calls[0].lineno >= min(
        node.lineno for node in weather_imports
    ):
        raise SealError("template does not refuse before importing live source")


def _render_python_wrapper(
    template: str,
    *,
    production_root: Path,
    production_python: Path,
    scope: Mapping[str, Any],
    source_sha256: Mapping[str, str],
    stage: str,
) -> str:
    rendered = _replace_once(template, "TEMPLATE_SEALED = False", "TEMPLATE_SEALED = True")
    rendered = _replace_once(
        rendered,
        '"__SEAL_PRODUCTION_ROOT__"',
        repr(str(production_root)),
    )
    rendered = _replace_once(
        rendered,
        '"__SEAL_PRODUCTION_PYTHON__"',
        repr(str(production_python)),
    )
    rendered = _replace_once(
        rendered,
        '"__SEAL_HARDENING_ANCESTOR__"',
        repr(REQUIRED_INTERRUPT_CLEANUP_ANCESTOR),
    )
    rendered = _replace_once(rendered, '"__SEAL_SCOPE__"', _python_literal(scope))
    rendered = _replace_once(
        rendered,
        '"__SEAL_SOURCE_SHA256__"',
        _python_literal(source_sha256),
    )
    cancellation_mode = None
    if stage != "stage0":
        cancellation_mode = (
            "cancel_all" if stage == "stage1_cancel_all" else "dead_man"
        )
        rendered = _replace_once(
            rendered,
            '"__SEAL_CANCELLATION_MODE__"',
            repr(cancellation_mode),
        )
        rendered = _replace_once(
            rendered,
            '"__SEAL_STAGE_NAME__"',
            repr(stage),
        )
    if TEMPLATE_MARKER_RE.search(rendered) or "UNSEALED" in rendered:
        raise SealError("generated Python wrapper retains an unsealed marker")
    try:
        tree = ast.parse(rendered)
    except SyntaxError as exc:
        raise SealError("generated Python wrapper failed AST parsing") from exc
    main_functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"
    ]
    if len(main_functions) != 1 or main_functions[0].args.args:
        raise SealError("generated Python wrapper does not have a no-argument main")
    if "argparse" in rendered or "parse_args" in rendered:
        raise SealError("generated Python wrapper exposes a parameter parser")
    if stage == "stage0":
        if "live_cli.run_stage0(" not in rendered or "live_cli.run_stage1(" in rendered:
            raise SealError("generated Stage 0 wrapper crossed its stage boundary")
    else:
        if (
            "live_cli.run_stage1(" not in rendered
            or f"CANCELLATION_MODE = {cancellation_mode!r}" not in rendered
            or "live_cli.run_stage0(" in rendered
            or "stage2" in rendered.lower()
        ):
            raise SealError("generated Stage 1 wrapper crossed its stage boundary")
    return rendered


def _render_launcher(
    template: str,
    *,
    production_root: Path,
    production_python: Path,
    wrapper_path: Path,
    wrapper_sha256: str,
    workload: str,
    execution_host_profile: str,
    execution_host_id: str,
    workload_sha256: str,
    job_helper_sha256: str,
    credential_manifest_path: Path,
    credential_manifest_sha256: str,
) -> str:
    values = {
        '"__SEAL_PRODUCTION_ROOT__"': str(production_root),
        '"__SEAL_PRODUCTION_PYTHON__"': str(production_python),
        '"__SEAL_WRAPPER_PATH__"': str(wrapper_path),
        '"__SEAL_WRAPPER_SHA256__"': wrapper_sha256,
        '"__SEAL_WORKLOAD__"': workload,
        '"__SEAL_EXECUTION_HOST_PROFILE__"': execution_host_profile,
        '"__SEAL_EXECUTION_HOST_ID__"': execution_host_id,
        '"__SEAL_WORKLOAD_ADMISSION_SHA256__"': workload_sha256,
        '"__SEAL_WINDOWS_JOB_HELPER_SHA256__"': job_helper_sha256,
        '"__SEAL_CREDENTIAL_MANIFEST_PATH__"': str(credential_manifest_path),
        '"__SEAL_CREDENTIAL_MANIFEST_SHA256__"': credential_manifest_sha256,
    }
    rendered = template
    for marker, value in values.items():
        rendered = _replace_once(rendered, marker, _powershell_literal(value))
    if TEMPLATE_MARKER_RE.search(rendered) or "UNSEALED" in rendered:
        raise SealError("generated launcher retains an unsealed marker")
    if re.search(r"param\s*\(\s*\)", rendered, flags=re.IGNORECASE) is None:
        raise SealError("generated launcher is not no-argument")
    if "$MyInvocation.UnboundArguments.Count -ne 0" not in rendered:
        raise SealError("generated launcher omits the runtime argument refusal")
    return rendered


def _write_new(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SealError(f"seal output already exists: {path}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        # Preserve a partial file as a fail-closed spent namespace.
        raise


def _validate_spec(
    spec_path: Path,
    *,
    now: datetime,
    template_root: Path,
    attempt_root_validator=validate_private_attempt_root,
    capture_assignment_validator=require_current_capture_execution_assignment,
    portable_assignment_validator=require_current_portable_execution_assignment,
) -> dict[str, Any]:
    spec, spec_raw = _read_json_object(spec_path, label="seal spec")
    _require_exact_keys(
        spec,
        {
            "schema_version",
            "stage",
            "prepared_at_local",
            "production",
            "scope",
            "inputs",
            "economics_acceptance",
            "reviewed_status_flags",
            "template_sha256",
            "source_sha256",
        },
        label="seal spec",
    )
    if spec["schema_version"] != SPEC_SCHEMA_VERSION:
        raise SealError("seal spec schema is unsupported")
    spec_economics_acceptance = _require_exact_keys(
        spec["economics_acceptance"],
        ECONOMICS_ACCEPTANCE_KEYS,
        label="economics_acceptance",
    )
    stage = str(spec["stage"])
    if stage not in STAGES:
        raise SealError("seal spec stage is unsupported")
    production = _require_exact_keys(
        spec["production"],
        {
            "root",
            "branch",
            "commit",
            "tree",
            "python",
            "git_executable",
            "git_executable_sha256",
            "canonical_origin_url",
        },
        label="production",
    )
    root_input = Path(str(production["root"]))
    if not root_input.is_absolute():
        raise SealError("production.root must be absolute")
    root = validate_nonreparse_directory(root_input)
    python_input = Path(str(production["python"]))
    if not python_input.is_absolute():
        raise SealError("production.python must be absolute")
    python = validate_regular_nonreparse_file(python_input)
    expected_python = (root / "venv/Scripts/python.exe").resolve()
    if not _same_path(python, expected_python) or not python.is_file():
        raise SealError("production interpreter is absent or not the canonical venv")
    git_input = Path(str(production["git_executable"] or ""))
    if not git_input.is_absolute():
        raise SealError("production.git_executable must be absolute")
    git_executable = validate_regular_nonreparse_file(git_input)
    git_sha256 = _require_sha256(
        production["git_executable_sha256"], label="production.git_executable_sha256"
    )
    if (
        not _same_path(git_executable, canonical_git_executable())
        or _sha256_file(git_executable) != git_sha256
        or production["canonical_origin_url"] != CANONICAL_ORIGIN_URL
    ):
        raise SealError("production Git executable or canonical origin binding is invalid")
    scope = _require_exact_keys(
        spec["scope"],
        {
            "target_date",
            "condition_id",
            "token_id",
            "requested_budget_pusd",
            "run_not_before_local",
            "run_not_after_local",
            "attempt_root",
            "lease_workload",
            "execution_host_profile",
            "execution_host_id",
            "market_id",
            "market_timezone",
        },
        label="scope",
    )
    try:
        target = date.fromisoformat(str(scope["target_date"]))
    except ValueError as exc:
        raise SealError("scope.target_date is invalid") from exc
    condition = str(scope["condition_id"] or "").lower()
    token = str(scope["token_id"] or "")
    if CONDITION_RE.fullmatch(condition) is None or TOKEN_RE.fullmatch(token) is None:
        raise SealError("condition or token scope is invalid")
    budget = _parse_decimal(scope["requested_budget_pusd"], label="requested budget")
    if budget != FIRST_TEST_REQUESTED_BUDGET_PUSD:
        raise SealError("first live test budget must be exactly 10 pUSD")
    prepared = _parse_aware(spec["prepared_at_local"], label="prepared_at_local")
    start = _parse_aware(scope["run_not_before_local"], label="run_not_before_local")
    stop = _parse_aware(scope["run_not_after_local"], label="run_not_after_local")
    now_utc = now.astimezone(timezone.utc)
    prepared_utc = prepared.astimezone(timezone.utc)
    if prepared_utc > now_utc + timedelta(seconds=5) or prepared_utc < now_utc - timedelta(
        minutes=5
    ):
        raise SealError("prepared_at_local is not current")
    if not start < stop or (stop - start).total_seconds() > MAX_RUN_WINDOW_SECONDS:
        raise SealError("reviewed run window is invalid or exceeds 30 minutes")
    contained_end = stop + timedelta(
        seconds=live_time_window.LIVE_WINDOW_CLEANUP_RESERVE_SECONDS
    )
    execution_host_profile = str(scope["execution_host_profile"] or "")
    if (
        execution_host_profile == CAPTURE_COLOCATED_HOST_PROFILE
        and any(
            value.astimezone(live_time_window.LIVE_WINDOW_TIMEZONE).date()
            != target
            for value in (start, stop, contained_end)
        )
    ):
        raise SealError("reviewed execution timestamps do not share the target date")
    execution_host_id = _require_sha256(
        scope["execution_host_id"], label="execution host id"
    )
    if execution_host_profile not in EXECUTION_HOST_PROFILES:
        raise SealError("execution host profile is unsupported")
    production_branch = str(production["branch"] or "")
    _require_authorized_branch(execution_host_profile, production_branch)
    if execution_host_id != current_execution_host_id():
        raise SealError("seal scope is bound to a different execution host")
    if execution_host_profile == PORTABLE_EXECUTION_HOST_PROFILE:
        try:
            portable_assignment_validator(
                root / EXECUTION_HOST_ASSIGNMENT_PATH,
                execution_host_id=execution_host_id,
                execution_principal_id=current_execution_principal_id(),
            )
        except Exception as exc:
            raise SealError(
                "current host/principal is not the active portable executor"
            ) from exc
    else:
        try:
            capture_assignment_validator(
                root / EXECUTION_HOST_ASSIGNMENT_PATH,
                execution_host_id=execution_host_id,
            )
        except Exception as exc:
            raise SealError(
                "current host is not eligible for capture-colocated execution"
            ) from exc
    if (
        execution_host_profile == CAPTURE_COLOCATED_HOST_PROFILE
        and not live_time_window.execution_window_is_supported(
            start, stop, target_date=target
        )
    ):
        raise SealError(
            "reviewed execution and cleanup window is outside the supported "
            "00:30-09:00 America/Toronto live window"
        )
    if not start.astimezone(timezone.utc) <= now_utc <= stop.astimezone(timezone.utc):
        raise SealError("sealer is outside the reviewed run window")
    if (
        execution_host_profile == CAPTURE_COLOCATED_HOST_PROFILE
        and prepared.astimezone(live_time_window.LIVE_WINDOW_TIMEZONE).date()
        != target
    ):
        raise SealError("reviewed timestamps do not share the target local date")
    workload = str(scope["lease_workload"] or "")
    if WORKLOAD_RE.fullmatch(workload) is None:
        raise SealError("lease workload name is invalid")
    attempt_root_input = Path(str(scope["attempt_root"]))
    if not attempt_root_input.is_absolute():
        raise SealError("attempt_root must be absolute")
    attempt_root = validate_nonreparse_directory(attempt_root_input)
    if _is_within(root, attempt_root) or _same_path(root, attempt_root):
        raise SealError("attempt root must be outside the production repository")
    try:
        attempt_root_security = dict(attempt_root_validator(attempt_root_input))
    except Exception as exc:
        raise SealError("attempt root failed private ACL/reparse validation") from exc
    if attempt_root_security.get("status") != "PASS":
        raise SealError("attempt root security validation did not pass")

    reviews = spec["reviewed_status_flags"]
    if not isinstance(reviews, list):
        raise SealError("reviewed_status_flags must be a list")
    normalized_reviews = []
    for index, item in enumerate(reviews):
        row = _require_exact_keys(
            item, {"sha256", "review"}, label=f"reviewed_status_flags[{index}]"
        )
        digest = _require_sha256(row["sha256"], label="reviewed status flag hash")
        review = str(row["review"] or "").strip()
        if len(review) < 12 or len(review) > 500:
            raise SealError("each allowed status flag needs a concise written review")
        normalized_reviews.append({"sha256": digest, "review": review})
    normalized_reviews.sort(key=lambda row: row["sha256"])
    if len({row["sha256"] for row in normalized_reviews}) != len(normalized_reviews):
        raise SealError("reviewed status flag hashes are not unique")
    if (
        execution_host_profile == PORTABLE_EXECUTION_HOST_PROFILE
        and normalized_reviews
    ):
        raise SealError(
            "portable execution hosts cannot inherit capture-host status exceptions"
        )

    expected_inputs = INPUT_LAYOUTS[stage]
    inputs = _require_exact_keys(
        spec["inputs"], set(expected_inputs), label="inputs"
    )
    normalized_inputs: dict[str, dict[str, str]] = {}
    for role, relative in expected_inputs.items():
        record = _require_exact_keys(
            inputs[role], {"path", "sha256"}, label=f"inputs.{role}"
        )
        path_input = Path(str(record["path"]))
        if not path_input.is_absolute():
            raise SealError(f"inputs.{role}.path must be absolute")
        path = validate_regular_nonreparse_file(path_input)
        expected_hash = _require_sha256(
            record["sha256"], label=f"inputs.{role}.sha256"
        )
        if relative is not None:
            canonical = (attempt_root / relative).resolve()
            if not _same_path(path, canonical):
                raise SealError(f"inputs.{role}.path is not the canonical attempt path")
        if not path.is_file() or _sha256_file(path) != expected_hash:
            raise SealError(f"inputs.{role} is absent or hash-mismatched")
        normalized_inputs[role] = {"path": str(path), "sha256": expected_hash}
    credential_reference_payload = _validate_credential_reference_manifest(
        Path(normalized_inputs["credential_reference_manifest"]["path"])
    )
    _validate_credential_import_receipt(
        Path(normalized_inputs["credential_import_receipt"]["path"]),
        required_mode=FIRST_SESSION_CREDENTIAL_MODE,
        now=now,
    )
    _validate_identity(
        Path(normalized_inputs["identity"]["path"]),
        requested_budget=budget,
        expected_reference=credential_reference_payload,
    )

    outputs = {
        role: (attempt_root / relative).resolve()
        for role, relative in OUTPUT_LAYOUTS[stage].items()
    }
    all_paths = [Path(row["path"]) for row in normalized_inputs.values()] + list(
        outputs.values()
    )
    if len({os.path.normcase(str(path)) for path in all_paths}) != len(all_paths):
        raise SealError("reviewed input and output paths are not distinct")
    if any(not _is_within(attempt_root, path) for path in outputs.values()):
        raise SealError("a planned output escapes the attempt root")
    if any(path.exists() for path in outputs.values()):
        raise SealError("every planned wrapper, receipt, sidecar, and runtime output must be new")

    template_hashes = _require_exact_keys(
        spec["template_sha256"],
        {"python", "launcher"},
        label="template_sha256",
    )
    python_template = (template_root / PYTHON_TEMPLATE_PATHS[stage]).resolve()
    launcher_template = (template_root / LAUNCHER_TEMPLATE_PATH).resolve()
    for role, path in (("python", python_template), ("launcher", launcher_template)):
        validate_regular_nonreparse_file(path)
        expected = _require_sha256(
            template_hashes[role], label=f"template_sha256.{role}"
        )
        if not path.is_file() or _sha256_file(path) != expected:
            raise SealError(f"reviewed {role} template hash does not match")

    expected_sources = set(LIVE_SOURCE_PATHS[stage]) | {WORKLOAD_ADMISSION_PATH}
    source_hashes = _require_exact_keys(
        spec["source_sha256"], expected_sources, label="source_sha256"
    )
    normalized_sources: dict[str, str] = {}
    for relative in sorted(expected_sources):
        expected = _require_sha256(
            source_hashes[relative], label=f"source_sha256.{relative}"
        )
        source_path = (root / relative).resolve()
        if not _is_within(root, source_path):
            raise SealError("reviewed source path escapes production")
        validate_regular_nonreparse_file(root / relative)
        if not source_path.is_file() or _sha256_file(source_path) != expected:
            raise SealError(f"reviewed source hash changed: {relative}")
        normalized_sources[relative] = expected

    candidate_role = "scope_plan" if stage == "stage0" else "candidate_plan"
    candidate = _validate_candidate(
        Path(normalized_inputs[candidate_role]["path"]),
        target_date=target.isoformat(),
        condition_id=condition,
        token_id=token,
        execution_host_profile=execution_host_profile,
        now=now,
        run_stop=stop,
    )
    if candidate["sha256"] != normalized_inputs[candidate_role]["sha256"]:
        raise SealError("candidate file hash changed during validation")
    if (
        candidate["market_id"] != scope["market_id"]
        or candidate["market_timezone"] != scope["market_timezone"]
    ):
        raise SealError("candidate market calendar differs from the reviewed scope")
    if execution_host_profile == PORTABLE_EXECUTION_HOST_PROFILE:
        market_timezone = ZoneInfo(candidate["market_timezone"])
        if any(
            value.astimezone(market_timezone).date() != target
            for value in (prepared, start, stop, contained_end)
        ):
            raise SealError(
                "portable execution timestamps do not share the market target date"
            )
    if dict(spec_economics_acceptance) != candidate["economics_acceptance"]:
        raise SealError(
            "candidate economics acceptance differs from the reviewed seal spec"
        )
    try:
        validate_bound_economics_acceptance_files(
            Path(normalized_inputs["accepted_economics_snapshot"]["path"]),
            Path(normalized_inputs["economics_drift_report"]["path"]),
            candidate["economics_acceptance"],
            target_date=target.isoformat(),
            current_snapshot_id=candidate["economics_snapshot_id"],
            current_snapshot_sha256=candidate["economics_snapshot_sha256"],
        )
    except RuntimeError as exc:
        raise SealError(
            "candidate economics acceptance does not match the sealed evidence"
        ) from exc
    if stage != "stage0":
        _validate_stage0_receipt(
            Path(normalized_inputs["stage0_receipt"]["path"]),
            target_date=target.isoformat(),
            condition_id=condition,
            token_id=token,
            budget=budget,
        )
        _validate_stage0_lineage(
            normalized_inputs,
            attempt_root=attempt_root,
            production_tip=_require_git_oid(
                production["commit"], label="production.commit"
            ),
            target_date=target.isoformat(),
            condition_id=condition,
            token_id=token,
            budget=budget,
            execution_host_profile=execution_host_profile,
            execution_host_id=execution_host_id,
            market_id=candidate["market_id"],
            market_timezone=candidate["market_timezone"],
        )
        if stage == "stage1_dead_man":
            _validate_cancel_all_predecessor(
                normalized_inputs,
                attempt_root=attempt_root,
                production_tip=_require_git_oid(
                    production["commit"], label="production.commit"
                ),
                target_date=target.isoformat(),
                condition_id=condition,
                token_id=token,
                budget=budget,
                execution_host_profile=execution_host_profile,
                execution_host_id=execution_host_id,
                market_id=candidate["market_id"],
                market_timezone=candidate["market_timezone"],
            )

    return {
        "spec": spec,
        "spec_raw": spec_raw,
        "spec_path": spec_path.resolve(),
        "stage": stage,
        "production": {
            "root": str(root),
            "branch": production_branch,
            "commit": _require_git_oid(production["commit"], label="production.commit"),
            "tree": _require_git_oid(production["tree"], label="production.tree"),
            "python": str(python),
            "git_executable": str(git_executable),
            "git_executable_sha256": git_sha256,
            "canonical_origin_url": CANONICAL_ORIGIN_URL,
        },
        "scope": {
            "target_date": target.isoformat(),
            "condition_id": condition,
            "token_id": token,
            "requested_budget_pusd": float(budget),
            "run_not_before_local": start.isoformat(),
            "run_not_after_local": stop.isoformat(),
            "attempt_root": str(attempt_root),
            "lease_workload": workload,
            "execution_host_profile": execution_host_profile,
            "execution_host_id": execution_host_id,
            "market_id": candidate["market_id"],
            "market_timezone": candidate["market_timezone"],
        },
        "prepared_at_local": prepared.isoformat(),
        "reviewed_status_flags": normalized_reviews,
        "inputs": normalized_inputs,
        "outputs": outputs,
        "templates": {
            "python": {
                "path": str(python_template),
                "sha256": _sha256_file(python_template),
            },
            "launcher": {
                "path": str(launcher_template),
                "sha256": _sha256_file(launcher_template),
            },
        },
        "source_sha256": normalized_sources,
        "candidate": candidate,
        "attempt_root_security": attempt_root_security,
    }


def _runtime_scope(validated: Mapping[str, Any]) -> dict[str, Any]:
    scope = validated["scope"]
    inputs = validated["inputs"]
    outputs = validated["outputs"]
    common = {
        "expected_production_tip": validated["production"]["commit"],
        "expected_production_tree": validated["production"]["tree"],
        "expected_production_branch": validated["production"]["branch"],
        "expected_remote_branch_ref": _remote_branch_ref(
            validated["production"]["branch"]
        ),
        "git_executable": validated["production"]["git_executable"],
        "git_executable_sha256": validated["production"][
            "git_executable_sha256"
        ],
        "canonical_origin_url": validated["production"]["canonical_origin_url"],
        "target_date": scope["target_date"],
        "condition_id": scope["condition_id"],
        "token_id": scope["token_id"],
        "requested_budget_pusd": scope["requested_budget_pusd"],
        "run_not_before_local": scope["run_not_before_local"],
        "run_not_after_local": scope["run_not_after_local"],
        "cleanup_reserve_seconds": live_time_window.LIVE_WINDOW_CLEANUP_RESERVE_SECONDS,
        "attempt_root": scope["attempt_root"],
        "expected_lease_workload": scope["lease_workload"],
        "execution_host_profile": scope["execution_host_profile"],
        "execution_host_id": scope["execution_host_id"],
        "market_id": scope["market_id"],
        "market_timezone": scope["market_timezone"],
        "allowed_status_flag_sha256": [
            row["sha256"] for row in validated["reviewed_status_flags"]
        ],
        "identity_path": inputs["identity"]["path"],
        "identity_sha256": inputs["identity"]["sha256"],
        "credential_import_receipt_path": inputs["credential_import_receipt"][
            "path"
        ],
        "credential_import_receipt_sha256": inputs["credential_import_receipt"][
            "sha256"
        ],
        "credential_reference_manifest_path": inputs[
            "credential_reference_manifest"
        ]["path"],
        "credential_reference_manifest_sha256": inputs[
            "credential_reference_manifest"
        ]["sha256"],
        "sdk_overlay_manifest_path": str(
            Path(validated["production"]["root"]) / SDK_OVERLAY_MANIFEST_PATH
        ),
        "sdk_overlay_manifest_sha256": validated["source_sha256"][
            SDK_OVERLAY_MANIFEST_PATH
        ],
        "doctor_receipt_out": str(outputs["doctor_receipt"]),
        "geography_precredential_receipt_out": str(
            outputs["geography_precredential_receipt"]
        ),
        "command_receipt_out": str(outputs["command_receipt"]),
        "user_stream_journal_out": str(outputs["user_stream_journal"]),
        "wrapper_execution_receipt_out": str(outputs["wrapper_execution_receipt"]),
    }
    if validated["stage"] == "stage0":
        common.update(
            {
                "scope_plan_path": inputs["scope_plan"]["path"],
                "scope_plan_sha256": inputs["scope_plan"]["sha256"],
                "geography_premutation_receipt_out": str(
                    outputs["geography_premutation_receipt"]
                ),
                "bootstrap_out": str(outputs["bootstrap"]),
            }
        )
    else:
        common.update(
            {
                "bootstrap_path": inputs["bootstrap"]["path"],
                "bootstrap_sha256": inputs["bootstrap"]["sha256"],
                "stage0_receipt_path": inputs["stage0_receipt"]["path"],
                "stage0_receipt_sha256": inputs["stage0_receipt"]["sha256"],
                "stage0_seal_receipt_path": inputs["stage0_seal_receipt"]["path"],
                "stage0_seal_receipt_sha256": inputs["stage0_seal_receipt"][
                    "sha256"
                ],
                "stage0_run_receipt_path": inputs["stage0_run_receipt"]["path"],
                "stage0_run_receipt_sha256": inputs["stage0_run_receipt"][
                    "sha256"
                ],
                "stage0_run_receipt_sidecar_path": inputs[
                    "stage0_run_receipt_sidecar"
                ]["path"],
                "stage0_run_receipt_sidecar_sha256": inputs[
                    "stage0_run_receipt_sidecar"
                ]["sha256"],
                "stage0_wrapper_execution_receipt_path": inputs[
                    "stage0_wrapper_execution_receipt"
                ]["path"],
                "stage0_wrapper_execution_receipt_sha256": inputs[
                    "stage0_wrapper_execution_receipt"
                ]["sha256"],
                "candidate_plan_path": inputs["candidate_plan"]["path"],
                "candidate_plan_sha256": inputs["candidate_plan"]["sha256"],
                "geography_presubmit_receipt_out": str(
                    outputs["geography_presubmit_receipt"]
                ),
                "result_out": str(outputs["result"]),
                "lifecycle_journal_out": str(outputs["lifecycle_journal"]),
            }
        )
        if validated["stage"] == "stage1_dead_man":
            for role in (
                "cancel_all_seal_receipt",
                "cancel_all_run_receipt",
                "cancel_all_run_receipt_sidecar",
                "cancel_all_wrapper_execution_receipt",
                "cancel_all_command_receipt",
                "cancel_all_result",
                "cancel_all_lifecycle_journal",
            ):
                common[f"{role}_path"] = inputs[role]["path"]
                common[f"{role}_sha256"] = inputs[role]["sha256"]
    return common


def _recheck_before_write(
    validated: Mapping[str, Any],
    *,
    git_runner: GitRunner,
) -> None:
    _verify_git_state(
        validated["production"],
        execution_host_profile=validated["scope"]["execution_host_profile"],
        git_runner=git_runner,
    )
    for record in validated["inputs"].values():
        path = Path(record["path"])
        if not path.is_file() or _sha256_file(path) != record["sha256"]:
            raise SealError("a reviewed input changed before seal publication")
    root = Path(validated["production"]["root"])
    for relative, expected in validated["source_sha256"].items():
        if _sha256_file(root / relative) != expected:
            raise SealError("a reviewed production source changed before seal publication")
    if any(path.exists() for path in validated["outputs"].values()):
        raise SealError("a planned output appeared before seal publication")


def seal_fixed_scope(
    spec_path: str | Path,
    *,
    now: datetime | None = None,
    git_runner: GitRunner = _default_git_runner,
    powershell_parser: PowerShellParser = _default_powershell_parser,
    sdk_validator: SdkValidator = _default_sdk_validator,
    attempt_root_validator=validate_private_attempt_root,
    capture_assignment_validator=require_current_capture_execution_assignment,
    portable_assignment_validator=require_current_portable_execution_assignment,
    template_root: str | Path | None = None,
    sealer_repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate *spec_path* and exclusively create its immutable seal artifacts."""

    assert_no_ambient_market_registry_override()
    current = now or datetime.now().astimezone()
    if current.tzinfo is None or current.utcoffset() is None:
        raise SealError("sealer clock must be timezone-aware")
    templates_root = validate_nonreparse_directory(template_root or REPO_ROOT)
    code_root = validate_nonreparse_directory(sealer_repo_root or REPO_ROOT)
    sealed_spec_path = validate_regular_nonreparse_file(spec_path)
    validated = _validate_spec(
        sealed_spec_path,
        now=current,
        template_root=templates_root,
        attempt_root_validator=attempt_root_validator,
        capture_assignment_validator=capture_assignment_validator,
        portable_assignment_validator=portable_assignment_validator,
    )
    production_root = Path(validated["production"]["root"])
    if not _same_path(code_root, production_root) or not _same_path(
        templates_root, production_root
    ):
        raise SealError("sealer code and templates must run from the reviewed production tree")
    seal_git_facts = _verify_git_state(
        validated["production"],
        execution_host_profile=validated["scope"]["execution_host_profile"],
        git_runner=git_runner,
    )
    sdk_validation = dict(
        sdk_validator(
            production_root / SDK_OVERLAY_MANIFEST_PATH,
            validated["source_sha256"][SDK_OVERLAY_MANIFEST_PATH],
        )
    )
    if sdk_validation.get("status") != "PASS":
        raise SealError("sealed SDK overlay validation did not pass")

    python_template = Path(validated["templates"]["python"]["path"]).read_text(
        encoding="utf-8"
    )
    launcher_template = Path(validated["templates"]["launcher"]["path"]).read_text(
        encoding="utf-8"
    )
    _validate_unsealed_template(python_template)
    runtime_scope = _runtime_scope(validated)
    wrapper_text = _render_python_wrapper(
        python_template,
        production_root=production_root,
        production_python=Path(validated["production"]["python"]),
        scope=runtime_scope,
        source_sha256=validated["source_sha256"],
        stage=validated["stage"],
    )
    wrapper_bytes = wrapper_text.encode("utf-8")
    wrapper_sha256 = _sha256_bytes(wrapper_bytes)
    launcher_text = _render_launcher(
        launcher_template,
        production_root=production_root,
        production_python=Path(validated["production"]["python"]),
        wrapper_path=validated["outputs"]["python_wrapper"],
        wrapper_sha256=wrapper_sha256,
        workload=validated["scope"]["lease_workload"],
        execution_host_profile=validated["scope"]["execution_host_profile"],
        execution_host_id=validated["scope"]["execution_host_id"],
        workload_sha256=validated["source_sha256"][WORKLOAD_ADMISSION_PATH],
        job_helper_sha256=validated["source_sha256"][WINDOWS_JOB_HELPER_PATH],
        credential_manifest_path=Path(
            validated["inputs"]["credential_reference_manifest"]["path"]
        ),
        credential_manifest_sha256=validated["inputs"][
            "credential_reference_manifest"
        ]["sha256"],
    )
    powershell_parser(launcher_text)
    launcher_bytes = launcher_text.encode("utf-8-sig")
    launcher_sha256 = _sha256_bytes(launcher_bytes)

    input_records = [
        {"role": role, **record}
        for role, record in sorted(validated["inputs"].items())
    ]
    output_records = [
        {"role": role, "path": str(path)}
        for role, path in sorted(validated["outputs"].items())
        if role not in {"python_wrapper", "launcher", "seal_receipt", "seal_receipt_sidecar"}
    ]
    live_sources = [
        {
            "path": str(production_root / relative),
            "repository_path": relative,
            "sha256": validated["source_sha256"][relative],
        }
        for relative in LIVE_SOURCE_PATHS[validated["stage"]]
    ]
    credential_record = validated["inputs"]["credential_import_receipt"]
    credential_reference_record = validated["inputs"][
        "credential_reference_manifest"
    ]
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "PASS",
        "stage": validated["stage"],
        "prepared_at_local": validated["prepared_at_local"],
        "seal_spec": {
            "path": str(validated["spec_path"]),
            "sha256": _sha256_bytes(validated["spec_raw"]),
        },
        "wrapper": {
            "path": str(validated["outputs"]["python_wrapper"]),
            "bytes": len(wrapper_bytes),
            "sha256": wrapper_sha256,
        },
        "launcher": {
            "path": str(validated["outputs"]["launcher"]),
            "bytes": len(launcher_bytes),
            "sha256": launcher_sha256,
        },
        "seal_receipt_path": str(validated["outputs"]["seal_receipt"]),
        "seal_receipt_sidecar_path": str(
            validated["outputs"]["seal_receipt_sidecar"]
        ),
        "templates": validated["templates"],
        "production": {
            "branch": validated["production"]["branch"],
            "commit": validated["production"]["commit"],
            "tree": validated["production"]["tree"],
            "local_branch_tip": seal_git_facts["local_branch_tip"],
            "cached_origin_branch_tip": seal_git_facts[
                "cached_origin_branch_tip"
            ],
            "remote_branch_tip": seal_git_facts["remote_branch_tip"],
            "remote_branch_ref": seal_git_facts["remote_branch_ref"],
            "live_remote_branch_equal": seal_git_facts[
                "live_remote_branch_equal"
            ],
            "local_master": seal_git_facts["local_master"],
            "cached_origin_master": seal_git_facts["cached_origin_master"],
            "remote_master": seal_git_facts["remote_master"],
            "remote_master_ref": REMOTE_MASTER_REF,
            "live_remote_master_equal": seal_git_facts[
                "live_remote_master_equal"
            ],
            "live_remote_master_ancestor": seal_git_facts[
                "live_remote_master_ancestor"
            ],
            "interpreter": validated["production"]["python"],
            "git_executable": validated["production"]["git_executable"],
            "git_executable_sha256": validated["production"][
                "git_executable_sha256"
            ],
            "canonical_origin_url": validated["production"][
                "canonical_origin_url"
            ],
            "required_interrupt_cleanup_ancestor": REQUIRED_INTERRUPT_CLEANUP_ANCESTOR,
        },
        "scope": {
            **validated["scope"],
            "cancellation_mode": (
                "not_applicable"
                if validated["stage"] == "stage0"
                else (
                    "cancel_all"
                    if validated["stage"] == "stage1_cancel_all"
                    else "dead_man"
                )
            ),
            "reviewed_status_flags": validated["reviewed_status_flags"],
        },
        "inputs": input_records,
        "planned_new_outputs": output_records,
        "candidate_validation": validated["candidate"],
        "sdk_overlay_validation": sdk_validation,
        "attempt_root_security": validated["attempt_root_security"],
        "live_source_modules": live_sources,
        "support_sources": [
            {
                "path": str(production_root / WORKLOAD_ADMISSION_PATH),
                "repository_path": WORKLOAD_ADMISSION_PATH,
                "sha256": validated["source_sha256"][WORKLOAD_ADMISSION_PATH],
            }
        ],
        "credential_import_receipt": credential_record,
        "credential_reference_manifest": credential_reference_record,
        "validation": {
            "python_ast": "PASS",
            "powershell_ast": "PASS",
            "no_argument_surface": "PASS",
            "no_unsealed_sentinel": "PASS",
            "unsealed_template_refusal": "PASS",
            "stage_isolation": "PASS",
            "output_new_distinct_contained": "PASS",
            "source_import_guard": "PASS",
            "candidate_ttl_and_scope": "PASS",
            "interrupt_cleanup_ancestry": "PASS",
            "live_remote_branch_equality": "PASS",
            "live_remote_master_baseline": "PASS",
            "reviewed_input_hashes": "PASS",
            "deterministic_render": "PASS",
        },
        "live_mutation_attempted": False,
        "credential_value_read": False,
    }
    receipt_bytes = _canonical_json(receipt)
    receipt_sha256 = _sha256_bytes(receipt_bytes)
    sidecar_bytes = (
        f"{receipt_sha256}  {validated['outputs']['seal_receipt'].name}\n"
    ).encode("ascii")

    _recheck_before_write(validated, git_runner=git_runner)
    if attempt_root_validator(
        Path(validated["scope"]["attempt_root"])
    ).get("status") != "PASS":
        raise SealError("attempt root security changed before seal publication")
    _write_new(validated["outputs"]["python_wrapper"], wrapper_bytes)
    _write_new(validated["outputs"]["launcher"], launcher_bytes)
    _write_new(validated["outputs"]["seal_receipt"], receipt_bytes)
    _write_new(validated["outputs"]["seal_receipt_sidecar"], sidecar_bytes)
    return {
        "status": "PASS",
        "stage": validated["stage"],
        "wrapper": receipt["wrapper"],
        "launcher": receipt["launcher"],
        "seal_receipt": {
            "path": str(validated["outputs"]["seal_receipt"]),
            "sha256": receipt_sha256,
        },
        "seal_receipt_sidecar": str(validated["outputs"]["seal_receipt_sidecar"]),
        "live_mutation_attempted": False,
        "credential_value_read": False,
    }


def build_public_inventory(
    stage: str,
    production_root: str | Path = REPO_ROOT,
    *,
    execution_host_profile: str,
    git_runner: GitRunner = _default_git_runner,
) -> dict[str, Any]:
    """Return public hashes needed to author a reviewed seal spec; write nothing."""

    assert_no_ambient_market_registry_override()
    if stage not in STAGES:
        raise SealError("inventory stage is unsupported")
    if execution_host_profile not in EXECUTION_HOST_PROFILES:
        raise SealError("inventory execution host profile is unsupported")
    root = Path(production_root).resolve()
    sources = list(LIVE_SOURCE_PATHS[stage]) + [WORKLOAD_ADMISSION_PATH]
    paths = {
        relative: _sha256_file(root / relative)
        for relative in sources
        if (root / relative).is_file()
    }
    templates = {
        "python": _sha256_file(root / PYTHON_TEMPLATE_PATHS[stage]),
        "launcher": _sha256_file(root / LAUNCHER_TEMPLATE_PATH),
    }
    python = root / "venv/Scripts/python.exe"
    git_executable = canonical_git_executable()
    bootstrap = {
        relative: _sha256_file(root / relative)
        for relative in SESSION_BOOTSTRAP_PATHS
        if (root / relative).is_file()
    }
    head = _git_text(git_runner, root, "rev-parse", "HEAD").lower()
    branch = _git_text(git_runner, root, "branch", "--show-current")
    remote_branch_ref = _remote_branch_ref(branch)
    local_branch_tip = _git_text(
        git_runner, root, "rev-parse", _local_branch_ref(branch)
    ).lower()
    cached_origin_branch_tip = _git_text(
        git_runner, root, "rev-parse", _cached_origin_branch_ref(branch)
    ).lower()
    local_master = _git_text(
        git_runner, root, "rev-parse", "refs/heads/master"
    ).lower()
    cached_origin_master = _git_text(
        git_runner, root, "rev-parse", "refs/remotes/origin/master"
    ).lower()
    try:
        remote_refs = _remote_ref_oids(
            git_runner,
            root,
            (REMOTE_MASTER_REF, remote_branch_ref),
        )
        remote_master = remote_refs[REMOTE_MASTER_REF]
        remote_branch_tip = remote_refs[remote_branch_ref]
    except SealError:
        remote_master = None
        remote_branch_tip = None
    live_remote_branch_equal = (
        remote_branch_tip is not None
        and head
        == local_branch_tip
        == cached_origin_branch_tip
        == remote_branch_tip
    )
    live_remote_master_equal = (
        remote_master is not None
        and local_master == cached_origin_master == remote_master
    )
    master_ancestry = (
        _git(
            git_runner,
            root,
            "merge-base",
            "--is-ancestor",
            remote_master,
            head,
            allowed=(0, 1),
        )
        if remote_master is not None
        else None
    )
    live_remote_master_ancestor = (
        master_ancestry is not None and master_ancestry.returncode == 0
    )
    hardening_ancestry = _git(
        git_runner,
        root,
        "merge-base",
        "--is-ancestor",
        REQUIRED_INTERRUPT_CLEANUP_ANCESTOR,
        head,
        allowed=(0, 1),
    )
    status_lines = [
        line
        for line in _git(
            git_runner,
            root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ).stdout.splitlines()
        if line.strip()
    ]
    worktree_policy_clean = _worktree_policy_clean(
        execution_host_profile,
        status_lines,
    )
    return {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "status": "PASS"
        if hardening_ancestry.returncode == 0
        and _branch_is_authorized(execution_host_profile, branch)
        and live_remote_branch_equal
        and live_remote_master_equal
        and live_remote_master_ancestor
        and worktree_policy_clean
        and len(paths) == len(sources)
        and python.is_file()
        and len(bootstrap) == len(SESSION_BOOTSTRAP_PATHS)
        else "BLOCK",
        "stage": stage,
        "execution_host_profile": execution_host_profile,
        "production": {
            "root": str(root),
            "branch": branch,
            "commit": head,
            "local_branch_tip": local_branch_tip,
            "cached_origin_branch_tip": cached_origin_branch_tip,
            "remote_branch_tip": remote_branch_tip,
            "remote_branch_ref": remote_branch_ref,
            "live_remote_branch_equal": live_remote_branch_equal,
            "local_master": local_master,
            "cached_origin_master": cached_origin_master,
            "remote_master": remote_master,
            "remote_master_ref": REMOTE_MASTER_REF,
            "live_remote_master_equal": live_remote_master_equal,
            "live_remote_master_ancestor": live_remote_master_ancestor,
            "worktree_policy_clean": worktree_policy_clean,
            "tree": _git_text(git_runner, root, "rev-parse", "HEAD^{tree}").lower(),
            "object_format": _git_text(
                git_runner, root, "rev-parse", "--show-object-format"
            ).lower(),
            "python": str(python.resolve()),
            "python_sha256": _sha256_file(python) if python.is_file() else None,
            "git_executable": str(git_executable),
            "git_executable_sha256": _sha256_file(git_executable),
            "canonical_origin_url": CANONICAL_ORIGIN_URL,
            "interrupt_cleanup_ancestor_integrated": (
                hardening_ancestry.returncode == 0
            ),
        },
        "template_sha256": templates,
        "source_sha256": dict(sorted(paths.items())),
        "session_bootstrap_sha256": dict(sorted(bootstrap.items())),
        "live_mutation_attempted": False,
        "credential_value_read": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory = subparsers.add_parser(
        "inventory", help="print public Git/template/source hashes and write nothing"
    )
    inventory.add_argument("--stage", choices=STAGES, required=True)
    inventory.add_argument("--production-root", default=str(REPO_ROOT))
    inventory.add_argument(
        "--execution-host-profile",
        choices=sorted(EXECUTION_HOST_PROFILES),
        required=True,
    )
    seal = subparsers.add_parser(
        "seal", help="seal one reviewed public spec without executing its wrapper"
    )
    seal.add_argument("--spec", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inventory":
            result = build_public_inventory(
                args.stage,
                args.production_root,
                execution_host_profile=args.execution_host_profile,
            )
            exit_code = 0 if result["status"] == "PASS" else 2
        else:
            result = seal_fixed_scope(args.spec)
            exit_code = 0
    except (SealError, OSError) as exc:
        result = {
            "status": "BLOCK",
            "operation": str(args.command),
            "exception_type": type(exc).__name__,
            "reason": str(exc),
            "live_mutation_attempted": False,
            "credential_value_read": False,
        }
        exit_code = 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
