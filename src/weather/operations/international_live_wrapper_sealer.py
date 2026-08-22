"""Deterministically seal one fixed-scope International Stage 0 or Stage 1 wrapper.

This module is preparation-only.  It reads public, content-bound inputs and
writes a no-argument wrapper, a no-argument launcher, and an immutable seal
receipt.  It imports only the inert SDK-tree validator; it never resolves
credentials, constructs an exchange client, or invokes a generated wrapper.
"""

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

from weather.paths import REPO_ROOT
from weather.schema_registry import schema_version


SPEC_SCHEMA_VERSION = schema_version("international_live_fixed_scope_seal_spec")
RECEIPT_SCHEMA_VERSION = schema_version("international_live_fixed_scope_seal")
INVENTORY_SCHEMA_VERSION = schema_version("international_live_fixed_scope_inventory")
REQUIRED_INTERRUPT_CLEANUP_ANCESTOR = (
    "da32c0895bb5b40c842b35232ff266c7968d4439"
)
CANDIDATE_SCHEMA_VERSION = "mm_live_market_candidate_plan_v0.2"
MAX_CANDIDATE_AGE_SECONDS = 300
MAX_PAPER_QUOTE_TTL_SECONDS = 120
MAX_RUN_WINDOW_SECONDS = 30 * 60
MAX_STAGE1_ORDER_NOTIONAL_PUSD = Decimal("10")
MAX_OPERATOR_BUDGET_PUSD = Decimal("100")
FIRST_TEST_REQUESTED_BUDGET_PUSD = Decimal("10")
FIRST_TEST_WALLET_CAP_PUSD = Decimal("100")
ALLOWED_DIRTY_PATHS = frozenset(
    {
        "config/location_market_events.json",
        "config/locations.json",
    }
)
CONDITION_RE = re.compile(r"^0x[0-9a-f]{64}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TOKEN_RE = re.compile(r"^[1-9][0-9]*$")
WORKLOAD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
TEMPLATE_MARKER_RE = re.compile(r"__SEAL_[A-Z0-9_]+__")

STAGES = ("stage0", "stage1_cancel_all", "stage1_dead_man")
PYTHON_TEMPLATE_PATHS = {
    "stage0": "scripts/ops/international_live_templates/stage0.py.tmpl",
    "stage1_cancel_all": (
        "scripts/ops/international_live_templates/stage1_cancel_all.py.tmpl"
    ),
    "stage1_dead_man": (
        "scripts/ops/international_live_templates/stage1_cancel_all.py.tmpl"
    ),
}
LAUNCHER_TEMPLATE_PATH = (
    "scripts/ops/international_live_templates/fixed_scope_launcher.ps1.tmpl"
)
WORKLOAD_ADMISSION_PATH = "scripts/ops/workload_admission.ps1"
SDK_OVERLAY_MANIFEST_PATH = (
    "scripts/ops/international_live_templates/sdk_overlay_manifest.json"
)
SDK_OVERLAY_MODULE_PATH = "src/weather/market/live_sdk_overlay.py"

LIVE_SOURCE_PATHS = {
    "stage0": (
        "src/weather/market/mm_live_pilot_cli.py",
        "src/weather/market/mm_live_bootstrap.py",
        "src/weather/market/mm_live_candidate_cli.py",
        "src/weather/market/mm_credentials.py",
        "src/weather/market/mm_official_adapter.py",
        "src/weather/market/mm_official_transport.py",
        "src/weather/market/mm_user_stream.py",
        SDK_OVERLAY_MODULE_PATH,
        SDK_OVERLAY_MANIFEST_PATH,
    ),
    "stage1_cancel_all": (
        "src/weather/market/mm_live_pilot_cli.py",
        "src/weather/market/mm_live_bootstrap.py",
        "src/weather/market/mm_live_lifecycle_probe.py",
        "src/weather/market/mm_live_candidate_cli.py",
        "src/weather/market/mm_credentials.py",
        "src/weather/market/mm_official_adapter.py",
        "src/weather/market/mm_official_transport.py",
        "src/weather/market/mm_user_stream.py",
        SDK_OVERLAY_MODULE_PATH,
        SDK_OVERLAY_MANIFEST_PATH,
    ),
    "stage1_dead_man": (
        "src/weather/market/mm_live_pilot_cli.py",
        "src/weather/market/mm_live_bootstrap.py",
        "src/weather/market/mm_live_lifecycle_probe.py",
        "src/weather/market/mm_live_candidate_cli.py",
        "src/weather/market/mm_credentials.py",
        "src/weather/market/mm_official_adapter.py",
        "src/weather/market/mm_official_transport.py",
        "src/weather/market/mm_user_stream.py",
        SDK_OVERLAY_MODULE_PATH,
        SDK_OVERLAY_MANIFEST_PATH,
    ),
}

INPUT_LAYOUTS = {
    "stage0": {
        "identity": "inputs/stage0-identity.json",
        "scope_plan": "inputs/stage0-scope-plan.json",
        "credential_import_receipt": None,
        "credential_reference_manifest": None,
    },
    "stage1_cancel_all": {
        "identity": "inputs/stage1-identity.json",
        "bootstrap": "stage0/bootstrap.json",
        "stage0_receipt": "stage0/command-receipt.json",
        "stage0_seal_receipt": "seal/stage0-seal-receipt.json",
        "stage0_wrapper_execution_receipt": "stage0/wrapper-execution-receipt.json",
        "candidate_plan": "inputs/stage1-cancel-all-candidate.json",
        "credential_import_receipt": None,
        "credential_reference_manifest": None,
    },
    "stage1_dead_man": {
        "identity": "inputs/stage1-dead-man-identity.json",
        "bootstrap": "stage0/bootstrap.json",
        "stage0_receipt": "stage0/command-receipt.json",
        "stage0_seal_receipt": "seal/stage0-seal-receipt.json",
        "stage0_wrapper_execution_receipt": "stage0/wrapper-execution-receipt.json",
        "candidate_plan": "inputs/stage1-dead-man-candidate.json",
        "credential_import_receipt": None,
        "credential_reference_manifest": None,
    },
}

OUTPUT_LAYOUTS = {
    "stage0": {
        "python_wrapper": "wrappers/stage0.py",
        "launcher": "wrappers/stage0.ps1",
        "doctor_receipt": "stage0/doctor-receipt.json",
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
    return subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=False,
    )


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


def _default_powershell_parser(source: str) -> None:
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / (
        "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
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
    git_runner: GitRunner,
) -> dict[str, Any]:
    root = Path(str(production["root"])).resolve()
    expected_commit = _require_sha256(production["commit"], label="production.commit")
    expected_tree = _require_sha256(production["tree"], label="production.tree")
    if production["branch"] != "master":
        raise SealError("fixed-scope sealing is restricted to production master")
    facts = {
        "head": _git_text(git_runner, root, "rev-parse", "HEAD").lower(),
        "master": _git_text(git_runner, root, "rev-parse", "master").lower(),
        "origin_master": _git_text(
            git_runner, root, "rev-parse", "origin/master"
        ).lower(),
        "tree": _git_text(git_runner, root, "rev-parse", "HEAD^{tree}").lower(),
        "branch": _git_text(git_runner, root, "branch", "--show-current"),
    }
    if not (
        facts["head"]
        == facts["master"]
        == facts["origin_master"]
        == expected_commit
    ):
        raise SealError("production HEAD/master/origin does not match the reviewed commit")
    if facts["tree"] != expected_tree or facts["branch"] != "master":
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
    dirty = {
        line[3:].replace("\\", "/")
        for line in _git_text(
            git_runner,
            root,
            "status",
            "--porcelain=v1",
            "--untracked-files=no",
        ).splitlines()
        if line.strip()
    }
    if not dirty.issubset(ALLOWED_DIRTY_PATHS):
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
    now: datetime,
    run_stop: datetime,
) -> dict[str, Any]:
    payload, raw = _read_json_object(path, label="candidate plan")
    selected = payload.get("selected")
    if not isinstance(selected, dict):
        raise SealError("candidate plan has no selected scope")
    paper = selected.get("paper_quote_proof")
    intent = selected.get("stage1_intent")
    policy = payload.get("selection_policy")
    if not isinstance(paper, dict) or not isinstance(intent, dict) or not isinstance(
        policy, dict
    ):
        raise SealError("candidate plan omits paper, intent, or policy evidence")
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
    paper_ttl = _parse_decimal(
        paper.get("quote_ttl_seconds"), label="paper quote TTL"
    )
    expected_paper_expiry = paper_generated + timedelta(seconds=float(paper_ttl))
    expected_effective_expiry = min(
        created + timedelta(seconds=MAX_CANDIDATE_AGE_SECONDS),
        paper_expires,
    )
    now_utc = now.astimezone(timezone.utc)
    stop_utc = run_stop.astimezone(timezone.utc)
    checks = {
        "schema": payload.get("schema_version") == CANDIDATE_SCHEMA_VERSION,
        "status": payload.get("status") == "PASS",
        "semantic_hash": payload.get("plan_sha256")
        == _canonical_payload_sha256(payload, omit="plan_sha256"),
        "non_authorizing": payload.get("selection_is_trading_authorization") is False,
        "target_date": payload.get("target_date") == target_date,
        "scope": str(selected.get("condition_id") or "").lower() == condition_id
        and str(selected.get("token_id") or "") == token_id,
        "constrained_scope": str(expected_scope.get("condition_id") or "").lower()
        == condition_id
        and str(expected_scope.get("token_id") or "") == token_id,
        "paper_scope": str(paper.get("condition_id") or "").lower() == condition_id
        and str(paper.get("token_id") or "") == token_id,
        "paper_permission": paper.get("quote_permission") is True
        and paper.get("live_trade_permission") is False,
        "paper_ttl": Decimal("0") < paper_ttl <= MAX_PAPER_QUOTE_TTL_SECONDS,
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
        "remaining_seconds_at_seal": (
            expires.astimezone(timezone.utc) - now_utc
        ).total_seconds(),
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
        payload.get("schema_version") == "mm_live_pilot_command_receipt_v0.1",
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


def _validate_credential_reference_manifest(path: Path) -> None:
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
        or any(
            re.fullmatch(r"wincred://[^\s]+", str(value or "")) is None
            for value in references.values()
        )
        or re.fullmatch(r"0x[0-9a-fA-F]{40}", str(payload["funder_address"] or ""))
        is None
        or str(public["POLYMARKET_FUNDER_ADDRESS"]).lower()
        != str(payload["funder_address"]).lower()
    ):
        raise SealError("credential reference manifest is not the exact public contract")


def _validate_credential_import_receipt(path: Path) -> None:
    payload, _raw = _read_json_object(path, label="credential import receipt")
    required = {
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
    _require_exact_keys(payload, required, label="credential import receipt")
    checks = payload.get("checks")
    if (
        payload["schema_version"] != "mm_live_credential_import_receipt_v0.1"
        or payload["status"] != "PASS"
        or payload["platform"] != "polymarket_global"
        or payload["credential_value_count_expected"] != 4
        or payload["credential_value_count_written"] != 4
        or payload["credential_values_retained"] is not False
        or payload["rollback_attempted"] is not False
        or payload["rollback_ok"] is not None
        or payload["missing"] != []
        or not isinstance(checks, dict)
        or not checks
        or any(value is not True for value in checks.values())
    ):
        raise SealError("credential import receipt is not an exact clean PASS")


def _validate_identity(path: Path, *, requested_budget: Decimal) -> None:
    payload, _raw = _read_json_object(path, label="Stage 0 identity")
    try:
        wallet_cap = Decimal(str(payload.get("pilot_wallet_max_funding_usdc")))
    except (InvalidOperation, TypeError, ValueError):
        wallet_cap = Decimal("-1")
    if (
        payload.get("schema_version") != "mm_stage0_client_identity_v0.2"
        or payload.get("platform") != "polymarket_global"
        or wallet_cap != FIRST_TEST_WALLET_CAP_PUSD
        or requested_budget != FIRST_TEST_REQUESTED_BUDGET_PUSD
        or requested_budget > wallet_cap
    ):
        raise SealError("identity does not bind the 10 pUSD request and 100 pUSD wallet cap")


def _validate_stage0_lineage(
    inputs: Mapping[str, Mapping[str, str]],
    *,
    production_tip: str,
    target_date: str,
    condition_id: str,
    token_id: str,
    budget: Decimal,
) -> None:
    seal, _raw = _read_json_object(
        Path(inputs["stage0_seal_receipt"]["path"]),
        label="Stage 0 seal receipt",
    )
    execution, _raw = _read_json_object(
        Path(inputs["stage0_wrapper_execution_receipt"]["path"]),
        label="Stage 0 wrapper execution receipt",
    )
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
        str(seal_scope.get("condition_id") or "").lower() == condition_id,
        str(seal_scope.get("token_id") or "") == token_id,
        seal_budget == budget,
        seal_credential.get("path") == expected_credential["path"],
        seal_credential.get("sha256") == expected_credential["sha256"],
        seal_reference.get("path") == expected_reference["path"],
        seal_reference.get("sha256") == expected_reference["sha256"],
        execution.get("schema_version")
        == "international_live_fixed_scope_execution_v0.2",
        execution.get("status") == "PASS",
        execution.get("stage") == "stage0",
        execution.get("production_tip") == production_tip,
        execution.get("target_date") == target_date,
        str(execution.get("condition_id") or "").lower() == condition_id,
        str(execution.get("token_id") or "") == token_id,
        execution_budget == budget,
        execution.get("exception_type") is None,
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
    )
    if not all(checks):
        raise SealError("Stage 0 seal/execution lineage does not bind Stage 1")


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
    workload_sha256: str,
    credential_manifest_path: Path,
    credential_manifest_sha256: str,
) -> str:
    values = {
        '"__SEAL_PRODUCTION_ROOT__"': str(production_root),
        '"__SEAL_PRODUCTION_PYTHON__"': str(production_python),
        '"__SEAL_WRAPPER_PATH__"': str(wrapper_path),
        '"__SEAL_WRAPPER_SHA256__"': wrapper_sha256,
        '"__SEAL_WORKLOAD__"': workload,
        '"__SEAL_WORKLOAD_ADMISSION_SHA256__"': workload_sha256,
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
    if "$args.Count -ne 0" not in rendered:
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
            "reviewed_status_flags",
            "template_sha256",
            "source_sha256",
        },
        label="seal spec",
    )
    if spec["schema_version"] != SPEC_SCHEMA_VERSION:
        raise SealError("seal spec schema is unsupported")
    stage = str(spec["stage"])
    if stage not in STAGES:
        raise SealError("seal spec stage is unsupported")
    production = _require_exact_keys(
        spec["production"],
        {"root", "branch", "commit", "tree", "python"},
        label="production",
    )
    root = _require_absolute_path(production["root"], label="production.root")
    python = _require_absolute_path(production["python"], label="production.python")
    expected_python = (root / "venv/Scripts/python.exe").resolve()
    if not _same_path(python, expected_python) or not python.is_file():
        raise SealError("production interpreter is absent or not the canonical venv")
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
    if not start.astimezone(timezone.utc) <= now_utc <= stop.astimezone(timezone.utc):
        raise SealError("sealer is outside the reviewed run window")
    if start.date() != target or stop.date() != target or prepared.date() != target:
        raise SealError("reviewed timestamps do not share the target local date")
    workload = str(scope["lease_workload"] or "")
    if WORKLOAD_RE.fullmatch(workload) is None:
        raise SealError("lease workload name is invalid")
    attempt_root = _require_absolute_path(scope["attempt_root"], label="attempt_root")
    if not attempt_root.is_dir():
        raise SealError("attempt root must already exist")
    if _is_within(root, attempt_root) or _same_path(root, attempt_root):
        raise SealError("attempt root must be outside the production repository")

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

    expected_inputs = INPUT_LAYOUTS[stage]
    inputs = _require_exact_keys(
        spec["inputs"], set(expected_inputs), label="inputs"
    )
    normalized_inputs: dict[str, dict[str, str]] = {}
    for role, relative in expected_inputs.items():
        record = _require_exact_keys(
            inputs[role], {"path", "sha256"}, label=f"inputs.{role}"
        )
        path = _require_absolute_path(record["path"], label=f"inputs.{role}.path")
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
    _validate_credential_reference_manifest(
        Path(normalized_inputs["credential_reference_manifest"]["path"])
    )
    _validate_credential_import_receipt(
        Path(normalized_inputs["credential_import_receipt"]["path"])
    )
    _validate_identity(
        Path(normalized_inputs["identity"]["path"]),
        requested_budget=budget,
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
        if not source_path.is_file() or _sha256_file(source_path) != expected:
            raise SealError(f"reviewed source hash changed: {relative}")
        normalized_sources[relative] = expected

    candidate_role = "scope_plan" if stage == "stage0" else "candidate_plan"
    candidate = _validate_candidate(
        Path(normalized_inputs[candidate_role]["path"]),
        target_date=target.isoformat(),
        condition_id=condition,
        token_id=token,
        now=now,
        run_stop=stop,
    )
    if candidate["sha256"] != normalized_inputs[candidate_role]["sha256"]:
        raise SealError("candidate file hash changed during validation")
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
            production_tip=_require_sha256(
                production["commit"], label="production.commit"
            ),
            target_date=target.isoformat(),
            condition_id=condition,
            token_id=token,
            budget=budget,
        )

    return {
        "spec": spec,
        "spec_raw": spec_raw,
        "spec_path": spec_path.resolve(),
        "stage": stage,
        "production": {
            "root": str(root),
            "branch": "master",
            "commit": _require_sha256(production["commit"], label="production.commit"),
            "tree": _require_sha256(production["tree"], label="production.tree"),
            "python": str(python),
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
    }


def _runtime_scope(validated: Mapping[str, Any]) -> dict[str, Any]:
    scope = validated["scope"]
    inputs = validated["inputs"]
    outputs = validated["outputs"]
    common = {
        "expected_production_tip": validated["production"]["commit"],
        "expected_production_tree": validated["production"]["tree"],
        "target_date": scope["target_date"],
        "condition_id": scope["condition_id"],
        "token_id": scope["token_id"],
        "requested_budget_pusd": scope["requested_budget_pusd"],
        "run_not_before_local": scope["run_not_before_local"],
        "run_not_after_local": scope["run_not_after_local"],
        "attempt_root": scope["attempt_root"],
        "expected_lease_workload": scope["lease_workload"],
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
        "command_receipt_out": str(outputs["command_receipt"]),
        "user_stream_journal_out": str(outputs["user_stream_journal"]),
        "wrapper_execution_receipt_out": str(outputs["wrapper_execution_receipt"]),
    }
    if validated["stage"] == "stage0":
        common.update(
            {
                "scope_plan_path": inputs["scope_plan"]["path"],
                "scope_plan_sha256": inputs["scope_plan"]["sha256"],
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
                "stage0_wrapper_execution_receipt_path": inputs[
                    "stage0_wrapper_execution_receipt"
                ]["path"],
                "stage0_wrapper_execution_receipt_sha256": inputs[
                    "stage0_wrapper_execution_receipt"
                ]["sha256"],
                "candidate_plan_path": inputs["candidate_plan"]["path"],
                "candidate_plan_sha256": inputs["candidate_plan"]["sha256"],
                "result_out": str(outputs["result"]),
                "lifecycle_journal_out": str(outputs["lifecycle_journal"]),
            }
        )
    return common


def _recheck_before_write(
    validated: Mapping[str, Any],
    *,
    git_runner: GitRunner,
) -> None:
    _verify_git_state(validated["production"], git_runner=git_runner)
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
    template_root: str | Path | None = None,
    sealer_repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate *spec_path* and exclusively create its immutable seal artifacts."""

    current = now or datetime.now().astimezone()
    if current.tzinfo is None or current.utcoffset() is None:
        raise SealError("sealer clock must be timezone-aware")
    templates_root = Path(template_root or REPO_ROOT).resolve()
    code_root = Path(sealer_repo_root or REPO_ROOT).resolve()
    validated = _validate_spec(Path(spec_path).resolve(), now=current, template_root=templates_root)
    production_root = Path(validated["production"]["root"])
    if not _same_path(code_root, production_root) or not _same_path(
        templates_root, production_root
    ):
        raise SealError("sealer code and templates must run from the reviewed production tree")
    _verify_git_state(validated["production"], git_runner=git_runner)
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
        workload_sha256=validated["source_sha256"][WORKLOAD_ADMISSION_PATH],
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
            "interpreter": validated["production"]["python"],
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
    git_runner: GitRunner = _default_git_runner,
) -> dict[str, Any]:
    """Return public hashes needed to author a reviewed seal spec; write nothing."""

    if stage not in STAGES:
        raise SealError("inventory stage is unsupported")
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
    head = _git_text(git_runner, root, "rev-parse", "HEAD").lower()
    ancestry = _git(
        git_runner,
        root,
        "merge-base",
        "--is-ancestor",
        REQUIRED_INTERRUPT_CLEANUP_ANCESTOR,
        head,
        allowed=(0, 1),
    )
    return {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "status": "PASS" if ancestry.returncode == 0 and len(paths) == len(sources) else "BLOCK",
        "stage": stage,
        "production": {
            "root": str(root),
            "branch": _git_text(git_runner, root, "branch", "--show-current"),
            "commit": head,
            "tree": _git_text(git_runner, root, "rev-parse", "HEAD^{tree}").lower(),
            "python": str((root / "venv/Scripts/python.exe").resolve()),
            "interrupt_cleanup_ancestor_integrated": ancestry.returncode == 0,
        },
        "template_sha256": templates,
        "source_sha256": dict(sorted(paths.items())),
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
    seal = subparsers.add_parser(
        "seal", help="seal one reviewed public spec without executing its wrapper"
    )
    seal.add_argument("--spec", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inventory":
            result = build_public_inventory(args.stage, args.production_root)
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
